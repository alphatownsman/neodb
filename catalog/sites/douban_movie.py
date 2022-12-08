from lxml import html
from catalog.common import *
from .douban import *
from catalog.movie.models import *
from catalog.tv.models import *
import logging
from django.db import models
from django.utils.translation import gettext_lazy as _
from .tmdb import TMDB_TV, search_tmdb_by_imdb_id


logger = logging.getLogger(__name__)


class MovieGenreEnum(models.TextChoices):
    DRAMA = 'Drama', _('剧情')
    KIDS = 'Kids', _('儿童')
    COMEDY = 'Comedy', _('喜剧')
    BIOGRAPHY = 'Biography', _('传记')
    ACTION = 'Action', _('动作')
    HISTORY = 'History', _('历史')
    ROMANCE = 'Romance', _('爱情')
    WAR = 'War', _('战争')
    SCI_FI = 'Sci-Fi', _('科幻')
    CRIME = 'Crime', _('犯罪')
    ANIMATION = 'Animation', _('动画')
    WESTERN = 'Western', _('西部')
    MYSTERY = 'Mystery', _('悬疑')
    FANTASY = 'Fantasy', _('奇幻')
    THRILLER = 'Thriller', _('惊悚')
    ADVENTURE = 'Adventure', _('冒险')
    HORROR = 'Horror', _('恐怖')
    DISASTER = 'Disaster', _('灾难')
    DOCUMENTARY = 'Documentary', _('纪录片')
    MARTIAL_ARTS = 'Martial-Arts', _('武侠')
    SHORT = 'Short', _('短片')
    ANCIENT_COSTUM = 'Ancient-Costum', _('古装')
    EROTICA = 'Erotica', _('情色')
    SPORT = 'Sport', _('运动')
    GAY_LESBIAN = 'Gay/Lesbian', _('同性')
    OPERA = 'Opera', _('戏曲')
    MUSIC = 'Music', _('音乐')
    FILM_NOIR = 'Film-Noir', _('黑色电影')
    MUSICAL = 'Musical', _('歌舞')
    REALITY_TV = 'Reality-TV', _('真人秀')
    FAMILY = 'Family', _('家庭')
    TALK_SHOW = 'Talk-Show', _('脱口秀')
    NEWS = 'News', _('新闻')
    SOAP = 'Soap', _('肥皂剧')
    TV_MOVIE = 'TV Movie', _('电视电影')
    THEATRE = 'Theatre', _('舞台艺术')
    OTHER = 'Other', _('其他')


# MovieGenreTranslator = ChoicesDictGenerator(MovieGenreEnum)


@SiteList.register
class DoubanMovie(AbstractSite):
    ID_TYPE = IdType.DoubanMovie
    URL_PATTERNS = [r"\w+://movie\.douban\.com/subject/(\d+)/{0,1}", r"\w+://m.douban.com/movie/subject/(\d+)/{0,1}"]
    WIKI_PROPERTY_ID = '?'
    # no DEFAULT_MODEL as it may be either TV Season and Movie

    @classmethod
    def id_to_url(self, id_value):
        return "https://movie.douban.com/subject/" + id_value + "/"

    def scrape(self):
        content = html.fromstring(DoubanDownloader(self.url).download().text.strip())

        try:
            raw_title = content.xpath(
                "//span[@property='v:itemreviewed']/text()")[0].strip()
        except IndexError:
            raise ParseError(self, 'title')

        orig_title = content.xpath(
            "//img[@rel='v:image']/@alt")[0].strip()
        title = raw_title.split(orig_title)[0].strip()
        # if has no chinese title
        if title == '':
            title = orig_title

        if title == orig_title:
            orig_title = None

        # there are two html formats for authors and translators
        other_title_elem = content.xpath(
            "//div[@id='info']//span[text()='又名:']/following-sibling::text()[1]")
        other_title = other_title_elem[0].strip().split(
            ' / ') if other_title_elem else None

        imdb_elem = content.xpath(
            "//div[@id='info']//span[text()='IMDb链接:']/following-sibling::a[1]/text()")
        if not imdb_elem:
            imdb_elem = content.xpath(
                "//div[@id='info']//span[text()='IMDb:']/following-sibling::text()[1]")
        imdb_code = imdb_elem[0].strip() if imdb_elem else None

        director_elem = content.xpath(
            "//div[@id='info']//span[text()='导演']/following-sibling::span[1]/a/text()")
        director = director_elem if director_elem else None

        playwright_elem = content.xpath(
            "//div[@id='info']//span[text()='编剧']/following-sibling::span[1]/a/text()")
        playwright = list(map(lambda a: a[:200], playwright_elem)) if playwright_elem else None

        actor_elem = content.xpath(
            "//div[@id='info']//span[text()='主演']/following-sibling::span[1]/a/text()")
        actor = list(map(lambda a: a[:200], actor_elem)) if actor_elem else None

        # construct genre translator
        genre_translator = {}
        attrs = [attr for attr in dir(MovieGenreEnum) if '__' not in attr]
        for attr in attrs:
            genre_translator[getattr(MovieGenreEnum, attr).label] = getattr(
                MovieGenreEnum, attr).value

        genre_elem = content.xpath("//span[@property='v:genre']/text()")
        if genre_elem:
            genre = []
            for g in genre_elem:
                g = g.split(' ')[0]
                if g == '紀錄片':  # likely some original data on douban was corrupted
                    g = '纪录片'
                elif g == '鬼怪':
                    g = '惊悚'
                if g in genre_translator:
                    genre.append(genre_translator[g])
                elif g in genre_translator.values():
                    genre.append(g)
                else:
                    logger.error(f'unable to map genre {g}')
        else:
            genre = None

        showtime_elem = content.xpath(
            "//span[@property='v:initialReleaseDate']/text()")
        if showtime_elem:
            showtime = []
            for st in showtime_elem:
                parts = st.split('(')
                if len(parts) == 1:
                    time = st.split('(')[0]
                    region = ''
                else:
                    time = st.split('(')[0]
                    region = st.split('(')[1][0:-1]
                showtime.append({time: region})
        else:
            showtime = None

        site_elem = content.xpath(
            "//div[@id='info']//span[text()='官方网站:']/following-sibling::a[1]/@href")
        site = site_elem[0].strip()[:200] if site_elem else None
        if site and not re.match(r'http.+', site):
            site = None

        area_elem = content.xpath(
            "//div[@id='info']//span[text()='制片国家/地区:']/following-sibling::text()[1]")
        if area_elem:
            area = [a.strip()[:100] for a in area_elem[0].split('/')]
        else:
            area = None

        language_elem = content.xpath(
            "//div[@id='info']//span[text()='语言:']/following-sibling::text()[1]")
        if language_elem:
            language = [a.strip() for a in language_elem[0].split(' / ')]
        else:
            language = None

        year_elem = content.xpath("//span[@class='year']/text()")
        year = int(re.search(r'\d+', year_elem[0])[0]) if year_elem and re.search(r'\d+', year_elem[0]) else None

        duration_elem = content.xpath("//span[@property='v:runtime']/text()")
        other_duration_elem = content.xpath(
            "//span[@property='v:runtime']/following-sibling::text()[1]")
        if duration_elem:
            duration = duration_elem[0].strip()
            if other_duration_elem:
                duration += other_duration_elem[0].rstrip()
            duration = duration.split('/')[0].strip()
        else:
            duration = None

        season_elem = content.xpath(
            "//*[@id='season']/option[@selected='selected']/text()")
        if not season_elem:
            season_elem = content.xpath(
                "//div[@id='info']//span[text()='季数:']/following-sibling::text()[1]")
            season = int(season_elem[0].strip()) if season_elem else None
        else:
            season = int(season_elem[0].strip())

        episodes_elem = content.xpath(
            "//div[@id='info']//span[text()='集数:']/following-sibling::text()[1]")
        episodes = int(episodes_elem[0].strip()) if episodes_elem and episodes_elem[0].strip().isdigit() else None

        single_episode_length_elem = content.xpath(
            "//div[@id='info']//span[text()='单集片长:']/following-sibling::text()[1]")
        single_episode_length = single_episode_length_elem[0].strip(
        )[:100] if single_episode_length_elem else None

        # if has field `episodes` not none then must be series
        is_series = True if episodes else False

        brief_elem = content.xpath("//span[@class='all hidden']")
        if not brief_elem:
            brief_elem = content.xpath("//span[@property='v:summary']")
        brief = '\n'.join([e.strip() for e in brief_elem[0].xpath(
            './text()')]) if brief_elem else None

        img_url_elem = content.xpath("//img[@rel='v:image']/@src")
        img_url = img_url_elem[0].strip() if img_url_elem else None

        pd = ResourceContent(metadata={
            'title': title,
            'orig_title': orig_title,
            'other_title': other_title,
            'imdb_code': imdb_code,
            'director': director,
            'playwright': playwright,
            'actor': actor,
            'genre': genre,
            'showtime': showtime,
            'site': site,
            'area': area,
            'language': language,
            'year': year,
            'duration': duration,
            'season_number': season,
            'episodes': episodes,
            'single_episode_length': single_episode_length,
            'brief': brief,
            'is_series': is_series,
            'cover_image_url': img_url,
        })
        pd.metadata['preferred_model'] = ('TVSeason' if season else 'TVShow') if is_series else 'Movie'

        if imdb_code:
            res_data = search_tmdb_by_imdb_id(imdb_code)
            tmdb_show_id = None
            if 'movie_results' in res_data and len(res_data['movie_results']) > 0:
                pd.metadata['preferred_model'] = 'Movie'
            elif 'tv_results' in res_data and len(res_data['tv_results']) > 0:
                pd.metadata['preferred_model'] = 'TVShow'
            elif 'tv_season_results' in res_data and len(res_data['tv_season_results']) > 0:
                pd.metadata['preferred_model'] = 'TVSeason'
                tmdb_show_id = res_data['tv_season_results'][0]['show_id']
            elif 'tv_episode_results' in res_data and len(res_data['tv_episode_results']) > 0:
                pd.metadata['preferred_model'] = 'TVSeason'
                tmdb_show_id = res_data['tv_episode_results'][0]['show_id']
                if res_data['tv_episode_results'][0]['episode_number'] != 1:
                    logger.error(f'Douban Movie {self.url} mapping to unexpected imdb episode {imdb_code}')
                    # TODO correct the IMDB id
            pd.lookup_ids[IdType.IMDB] = imdb_code
            if tmdb_show_id:
                pd.metadata['required_resources'] = [{
                    'model': 'TVShow',
                    'id_type': IdType.TMDB_TV,
                    'id_value': tmdb_show_id,
                    'title': title,
                    'url': TMDB_TV.id_to_url(tmdb_show_id),
                }]
        # TODO parse sister seasons
        # pd.metadata['related_resources'] = []
        if pd.metadata["cover_image_url"]:
            imgdl = BasicImageDownloader(pd.metadata["cover_image_url"], self.url)
            try:
                pd.cover_image = imgdl.download().content
                pd.cover_image_extention = imgdl.extention
            except Exception:
                logger.debug(f'failed to download cover for {self.url} from {pd.metadata["cover_image_url"]}')
        return pd
