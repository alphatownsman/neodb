import logging
import re
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from django.conf import settings
from django.core.validators import URLValidator

from catalog.common import (
    AbstractSite,
    BasicImageDownloader,
    CachedDownloader,
    IdType,
    ResourceContent,
    SiteManager,
    SiteName,
)
from catalog.common.downloaders import DownloadError
from catalog.common.scrapers import ParseError
from catalog.models import (
    Album,
    Edition,
    Game,
    Item,
    ItemCategory,
    Movie,
    Performance,
    PerformanceProduction,
    Podcast,
    TVEpisode,
    TVSeason,
    TVShow,
)
from catalog.search import ExternalSearchResultItem, record_search_failure
from common.models import SiteConfig

logger = logging.getLogger(__name__)


@SiteManager.register
class FediverseInstance(AbstractSite):
    SITE_NAME = SiteName.Fediverse
    ID_TYPE = IdType.Fediverse
    URL_PATTERNS = []
    WIKI_PROPERTY_ID = ""
    DEFAULT_MODEL = None
    id_type_mapping = {
        "isbn": IdType.ISBN,
        "imdb": IdType.IMDB,
        "barcode": IdType.GTIN,
    }
    supported_types = {
        "book": Edition,
        "edition": Edition,
        "movie": Movie,
        "tvshow": TVShow,
        "tvseason": TVSeason,
        "tvepisode": TVEpisode,
        "album": Album,
        "game": Game,
        "podcast": Podcast,
        "performance": Performance,
        "performanceproduction": PerformanceProduction,
    }
    request_header = {
        "User-Agent": settings.NEODB_USER_AGENT,
        "Accept": "application/activity+json",
    }

    @classmethod
    def id_to_url(cls, id_value):
        return id_value

    @classmethod
    def url_to_id(cls, url: str):
        u = url.split("://", 1)[1].split("?", 1)[0].split("/", 1)
        return "https://" + u[0].lower() + "/" + re.sub("^api/", "", u[1])
        # return "https://" + u[0].lower() + "/" + u[1]
        # FIXME re.sub(...) should be removed after all peers in network upgrade to 0.11.4.9+

    @classmethod
    def validate_url_fallback(cls, url: str):
        from takahe.utils import Takahe

        val = URLValidator()
        host = None
        try:
            val(url)
            u = cls.url_to_id(url)
            host = u.split("://", 1)[1].split("/", 1)[0].lower()
            if host in settings.SITE_DOMAINS:
                # disallow local instance URLs
                return False
            if host in Takahe.get_blocked_peers():
                return False
            return cls.get_json_from_url(u) is not None
        except DownloadError:
            if host and host in Takahe.get_neodb_peers():
                logger.warning(f"Fedi item url download error: {url}")
            return False
        except Exception as e:
            if host and host in Takahe.get_neodb_peers():
                logger.error(f"Fedi item url validation error: {url} {e}")
            return False

    @classmethod
    def is_local_item_url(cls, url: str) -> bool:
        """Check if the given URL belongs to a local item"""
        parsed = urlparse(url)
        if not parsed.hostname:
            return False
        # hostname drops any :port and userinfo; netloc keeps the port, which
        # SITE_DOMAINS may carry in local setups
        return (
            parsed.hostname in settings.SITE_DOMAINS
            or parsed.netloc.lower() in settings.SITE_DOMAINS
        )

    def get_local_item_from_external_resources(self) -> Item | None:
        """if a local item is in the external_resources, return it"""
        try:
            data = self.get_json_from_url(self.url)
        except DownloadError, ValueError:
            return None
        if not isinstance(data, dict):
            return None
        for ext in data.get("external_resources", []):
            u = ext.get("url")
            if u and self.is_local_item_url(u):
                i = Item.get_by_url(u, True)
                if i and not i.is_deleted:
                    return i

    @classmethod
    def get_json_from_url(cls, url):
        j = (
            CachedDownloader(url, headers=cls.request_header, timeout=2)
            .download()
            .json()
        )
        if (
            not isinstance(j, dict)
            or j.get("type", "").lower() not in cls.supported_types.keys()
        ):
            raise ValueError("Not a supported format or type")
        if j.get("id") != url:
            raise ValueError(f"ID mismatch: {j.get('id')} != {url}")
        return j

    def content_from_json(
        self, data: dict, detect_redirection: bool = True
    ) -> ResourceContent:
        """Build a ResourceContent from an item payload already in hand.

        Split out of scrape() so a caller holding the payload -- the
        catalog.ndjson of a backup -- can build the item without the origin
        server, which may be gone. Such a caller turns ``detect_redirection``
        off: its links already failed, so each HEAD only adds a timeout.
        """
        img_url = data.get("cover_image_url")
        raw_img, img_ext = (
            BasicImageDownloader.download_image(img_url, None, headers={})
            if img_url
            else (None, None)
        )
        ids = {}
        data["preferred_model"] = data.get("type", "")
        data["prematched_resources"] = []
        model_cls = self.supported_types.get(data["preferred_model"].lower())
        if not model_cls:
            raise ParseError(self, "preferred_model")
        # `or []`: external_resources is nullable in the item schema
        for ext in data.get("external_resources") or []:
            u = ext.get("url") if isinstance(ext, dict) else None
            if not u or self.is_local_item_url(u):
                continue
            site = SiteManager.get_site_by_url(u, detect_redirection=detect_redirection)
            if not site:
                logger.error(f"FediverseInstance: {self.url} unsupported url {u}")
                continue
            if site.ID_TYPE == IdType.Fediverse:
                # TODO add support to link across instances
                continue
            if not site.check_model_compatibility(model_cls):
                logger.error(f"FediverseInstance: {self.url} incompatible url {u}")
                continue
            ids[site.ID_TYPE] = site.id_value
        for k, v in self.id_type_mapping.items():
            d = data.get(k)
            if d:
                ids[v] = d
        d = ResourceContent(
            metadata=data,
            cover_image=raw_img,
            cover_image_extention=img_ext,
            lookup_ids=ids,
        )
        return d

    def scrape(self):
        data = self.get_json_from_url(self.url)
        return self.content_from_json(data)

    @classmethod
    async def peer_search_task(
        cls, host, q, page, category=None, page_size=5, endpoint: str | None = None
    ):
        p = (page - 1) * page_size // 20 + 1
        offset = (page - 1) * page_size % 20
        endpoint = cls.peer_search_endpoint(host, endpoint)
        api_url = f"{endpoint}{'&' if '?' in endpoint else '?'}query={quote_plus(q)}&page={p}{'&category=' + category if category and category != 'all' else ''}"
        async with httpx.AsyncClient() as client:
            results = []
            try:
                response = await client.get(
                    api_url,
                    timeout=2,
                )
                r = response.json()
            except Exception as e:
                logger.warning(
                    f"Fediverse search {host} error",
                    extra={"url": api_url, "query": q, "exception": e},
                )
                reason = "timeout" if isinstance(e, httpx.TimeoutException) else "error"
                record_search_failure("fediverse", reason)
                return []
            data = r.get("data") if isinstance(r, dict) else None
            for item in data if isinstance(data, list) else []:
                result = cls.peer_search_result(host, item)
                if result:
                    results.append(result)
        return results[offset : offset + page_size]

    @staticmethod
    def peer_search_result(host: str, item: object) -> ExternalSearchResultItem | None:
        """
        Peers may run older NeoDB or other software, so any field of an item
        may be missing or malformed; such an item is skipped, not fatal.
        """
        if not isinstance(item, dict):
            return None
        title = item.get("display_title")
        path = item.get("url")
        if not title or not isinstance(title, str) or not isinstance(path, str):
            return None
        try:
            # NeoDB returns a path; a full URL is accepted too
            url = urljoin(f"https://{host}/", path)
            if urlparse(url).scheme != "https":
                return None
            for res in item.get("external_resources") or []:
                if (
                    isinstance(res, dict)
                    and urlparse(str(res.get("url") or "")).hostname
                    in settings.SITE_DOMAINS
                ):
                    return None
        except ValueError, TypeError:
            return None
        try:
            cat = ItemCategory(item.get("category"))
        except ValueError:
            cat = None
        brief = item.get("brief")
        cover = item.get("cover_image_url")
        return ExternalSearchResultItem(
            cat,
            host,
            url,
            title,
            "",
            brief if isinstance(brief, str) else "",
            cover if isinstance(cover, str) else "",
        )

    @staticmethod
    def peer_search_endpoint(host: str, advertised: str | None) -> str:
        """
        Use the endpoint a peer advertises in nodeinfo only when it is https on
        the peer's own domain, so a peer cannot point every NeoDB instance's
        search traffic at a third-party host.
        """
        default = f"https://{host}/api/catalog/search"
        if not advertised:
            return default
        try:
            u = urlparse(advertised)
            h = (u.hostname or "").lower()
        except ValueError:
            return default
        if (
            u.scheme == "https"
            and not u.fragment
            and (h == host.lower() or h.endswith("." + host.lower()))
        ):
            return advertised
        return default

    @classmethod
    def get_peers_for_search(cls) -> list[str]:
        from takahe.utils import Takahe

        if SiteConfig.system.search_peers:  # '-' = disable federated search
            return (
                []
                if SiteConfig.system.search_peers == ["-"]
                else SiteConfig.system.search_peers
            )
        return Takahe.get_neodb_peers()

    @classmethod
    def search_tasks(
        cls, q: str, page: int = 1, category: str | None = None, page_size=5
    ):
        from takahe.utils import Takahe

        peers = cls.get_peers_for_search()
        if not peers:
            return []
        no_search, endpoints = Takahe.get_neodb_search_settings()
        c = category if category != "movietv" else "movie,tv"
        return [
            cls.peer_search_task(host, q, page, c, page_size, endpoints.get(host))
            for host in peers
            if host not in no_search
        ]
