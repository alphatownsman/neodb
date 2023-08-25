from typing import TYPE_CHECKING

from django.conf import settings

from .models import *

if TYPE_CHECKING:
    from users.models import APIdentity
    from users.models import User as NeoUser


def _int(s: str):
    try:
        return int(s)
    except:
        return -1


def _rating_to_emoji(score: int, star_mode=0):
    """convert score(0~10) to mastodon star emoji code"""
    if score is None or score == "" or score == 0:
        return ""
    solid_stars = score // 2
    half_star = int(bool(score % 2))
    empty_stars = 5 - solid_stars if not half_star else 5 - solid_stars - 1
    if star_mode == 1:
        emoji_code = "🌕" * solid_stars + "🌗" * half_star + "🌑" * empty_stars
    else:
        emoji_code = (
            settings.STAR_SOLID * solid_stars
            + settings.STAR_HALF * half_star
            + settings.STAR_EMPTY * empty_stars
        )
    emoji_code = emoji_code.replace("::", ": :")
    emoji_code = " " + emoji_code + " "
    return emoji_code


class Takahe:
    Visibilities = Post.Visibilities

    @staticmethod
    def get_domain():
        domain = settings.SITE_INFO["site_domain"]
        d = Domain.objects.filter(domain=domain).first()
        if not d:
            logger.info(f"Creating takahe domain {domain}")
            d = Domain.objects.create(
                domain=domain,
                local=True,
                service_domain=None,
                notes="NeoDB",
                nodeinfo=None,
            )
        return d

    @staticmethod
    def get_node_name_for_domain(d: str):
        domain = Domain.objects.filter(domain=d).first()
        if domain and domain.nodeinfo:
            return domain.nodeinfo.get("metadata", {}).get("nodeName")

    @staticmethod
    def init_identity_for_local_user(u: "NeoUser"):
        """
        When a new local NeoDB user is created,
        create a takahe user with the NeoDB user pk,
        create a takahe identity,
        then create a NeoDB APIdentity with the takahe identity pk.
        """
        from users.models import APIdentity

        if not u.username:
            logger.warning(f"User {u} has no username")
            return None
        user = User.objects.filter(pk=u.pk).first()
        handler = "@" + u.username
        if not user:
            logger.info(f"Creating takahe user {u}")
            user = User.objects.create(pk=u.pk, email=handler)
        else:
            if user.email != handler:
                logger.warning(f"Updating takahe user {u} email to {handler}")
                user.email = handler
                user.save()
        domain = Domain.objects.get(domain=settings.SITE_INFO["site_domain"])
        identity = Identity.objects.filter(username=u.username, local=True).first()
        if not identity:
            logger.info(f"Creating takahe identity {u}@{domain}")
            identity = Identity.objects.create(
                actor_uri=f"https://{domain.uri_domain}/@{u.username}@{domain.domain}/",
                username=u.username,
                domain=domain,
                name=u.username,
                local=True,
                discoverable=not u.preference.no_anonymous_view,
            )
            identity.generate_keypair()
        if not user.identities.filter(pk=identity.pk).exists():
            user.identities.add(identity)
        apidentity = APIdentity.objects.filter(pk=identity.pk).first()
        if not apidentity:
            logger.info(f"Creating APIdentity for {identity}")
            apidentity = APIdentity.objects.create(
                user=u,
                id=identity.pk,
                local=True,
                username=u.username,
                domain_name=domain.domain,
                deleted=identity.deleted,
            )
        elif apidentity.username != identity.username:
            logger.warning(
                f"Updating APIdentity {apidentity} username to {identity.username}"
            )
            apidentity.username = identity.username
            apidentity.save()
        if u.identity != apidentity:
            logger.warning(f"Linking user {u} identity to {apidentity}")
            u.identity = apidentity
            u.save(update_fields=["identity"])
        return apidentity

    @staticmethod
    def get_identity(pk: int):
        return Identity.objects.get(pk=pk)

    @staticmethod
    def get_identity_by_local_user(u: "NeoUser"):
        return (
            Identity.objects.filter(pk=u.identity.pk, local=True).first()
            if u and u.is_authenticated and u.identity
            else None
        )

    @staticmethod
    def get_or_create_apidentity(identity: Identity):
        from users.models import APIdentity

        apid = APIdentity.objects.filter(pk=identity.pk).first()
        if not apid:
            if identity.local:
                raise ValueError(f"local takahe identity {identity} missing APIdentity")
            if not identity.domain:
                raise ValueError(f"remote takahe identity {identity} missing domain")
            apid = APIdentity.objects.create(
                id=identity.pk,
                local=False,
                username=identity.username,
                domain_name=identity.domain.domain,
                deleted=identity.deleted,
            )
        return apid

    @staticmethod
    def get_local_user_by_identity(identity: Identity):
        from users.models import User as NeoUser

        return NeoUser.objects.get(identity_id=identity.pk) if identity.local else None

    @staticmethod
    def get_following_ids(identity_pk: int):
        targets = Follow.objects.filter(
            source_id=identity_pk, state="accepted"
        ).values_list("target", flat=True)
        return list(targets)

    @staticmethod
    def get_follower_ids(identity_pk: int):
        targets = Follow.objects.filter(
            target_id=identity_pk, state="accepted"
        ).values_list("target", flat=True)
        return list(targets)

    @staticmethod
    def get_following_request_ids(identity_pk: int):
        targets = Follow.objects.filter(
            source_id=identity_pk, state="pending_approval"
        ).values_list("target", flat=True)
        return list(targets)

    @staticmethod
    def get_requested_follower_ids(identity_pk: int):
        targets = Follow.objects.filter(
            target_id=identity_pk, state="pending_approval"
        ).values_list("target", flat=True)
        return list(targets)

    @staticmethod
    def update_follow_state(
        source_pk: int, target_pk: int, from_states: list[str], to_state: str
    ):
        follow = Follow.objects.filter(source_id=source_pk, target_id=target_pk).first()
        if (
            follow
            and (not from_states or follow.state in from_states)
            and follow.state != to_state
        ):
            follow.state = to_state
            follow.save()
        return follow

    @staticmethod
    def follow(source_pk: int, target_pk: int):
        try:
            follow = Follow.objects.get(source_id=source_pk, target_id=target_pk)
            if follow.state != "accepted":
                follow.state = "unrequested"
                follow.save()
        except Follow.DoesNotExist:
            source = Identity.objects.get(pk=source_pk)
            follow = Follow.objects.create(
                source_id=source_pk,
                target_id=target_pk,
                boosts=True,
                uri="",
                state="unrequested",
            )
            follow.uri = source.actor_uri + f"follow/{follow.pk}/"
            follow.save()

    @staticmethod
    def unfollow(source_pk: int, target_pk: int):
        Takahe.update_follow_state(source_pk, target_pk, [], "undone")
        # InboxMessage.create_internal(
        #     {
        #         "type": "ClearTimeline",
        #         "object": target_identity.pk,
        #         "actor": self.identity.pk,
        #     }
        # )

    @staticmethod
    def accept_follow_request(source_pk: int, target_pk: int):
        Takahe.update_follow_state(source_pk, target_pk, [], "accepting")

    @staticmethod
    def reject_follow_request(source_pk: int, target_pk: int):
        Takahe.update_follow_state(source_pk, target_pk, [], "rejecting")

    @staticmethod
    def get_muting_ids(identity_pk: int) -> list[int]:
        targets = Block.objects.filter(
            source_id=identity_pk,
            mute=True,
            state__in=["new", "sent", "awaiting_expiry"],
        ).values_list("target", flat=True)
        return list(targets)

    @staticmethod
    def get_blocking_ids(identity_pk: int) -> list[int]:
        targets = Block.objects.filter(
            source_id=identity_pk,
            mute=False,
            state__in=["new", "sent", "awaiting_expiry"],
        ).values_list("target", flat=True)
        return list(targets)

    @staticmethod
    def get_rejecting_ids(identity_pk: int) -> list[int]:
        pks1 = Block.objects.filter(
            source_id=identity_pk,
            mute=False,
            state__in=["new", "sent", "awaiting_expiry"],
        ).values_list("target", flat=True)
        pks2 = Block.objects.filter(
            target_id=identity_pk,
            mute=False,
            state__in=["new", "sent", "awaiting_expiry"],
        ).values_list("source", flat=True)
        return list(set(list(pks1) + list(pks2)))

    @staticmethod
    def block_or_mute(source_pk: int, target_pk: int, is_mute: bool):
        source = Identity.objects.get(pk=source_pk)
        if not source.local:
            raise ValueError(f"Cannot block/mute from remote identity {source}")
        with transaction.atomic():
            block, _ = Block.objects.update_or_create(
                defaults={"state": "new"},
                source_id=source_pk,
                target_id=target_pk,
                mute=is_mute,
            )
            if block.state != "new" or not block.uri:
                block.state = "new"
                block.uri = source.actor_uri + f"block/{block.pk}/"
                block.save()
            if not is_mute:
                Takahe.unfollow(source_pk, target_pk)
                Takahe.reject_follow_request(target_pk, source_pk)
            return block

    @staticmethod
    def undo_block_or_mute(source_pk: int, target_pk: int, is_mute: bool):
        Block.objects.filter(
            source_id=source_pk, target_id=target_pk, mute=is_mute
        ).update(state="undone")

    @staticmethod
    def block(source_pk: int, target_pk: int):
        return Takahe.block_or_mute(source_pk, target_pk, False)

    @staticmethod
    def unblock(source_pk: int, target_pk: int):
        return Takahe.undo_block_or_mute(source_pk, target_pk, False)

    @staticmethod
    def mute(source_pk: int, target_pk: int):
        return Takahe.block_or_mute(source_pk, target_pk, True)

    @staticmethod
    def unmute(source_pk: int, target_pk: int):
        return Takahe.undo_block_or_mute(source_pk, target_pk, True)

    @staticmethod
    def _force_state_cycle():  # for unit testing only
        Follow.objects.filter(
            state__in=["rejecting", "undone", "pending_removal"]
        ).delete()
        Follow.objects.all().update(state="accepted")
        Block.objects.filter(state="new").update(state="sent")
        Block.objects.exclude(state="sent").delete()

    @staticmethod
    def post(
        author_pk: int,
        pre_conetent: str,
        content: str,
        visibility: Visibilities,
        data: dict | None = None,
        post_pk: int | None = None,
        post_time: datetime.datetime | None = None,
    ) -> int | None:
        identity = Identity.objects.get(pk=author_pk)
        post = (
            Post.objects.filter(author=identity, pk=post_pk).first()
            if post_pk
            else None
        )
        if post:
            post.edit_local(
                pre_conetent, content, visibility=visibility, type_data=data
            )
        else:
            post = Post.create_local(
                identity,
                pre_conetent,
                content,
                visibility=visibility,
                type_data=data,
                published=post_time,
            )
        return post.pk if post else None

    @staticmethod
    def get_post_url(post_pk: int) -> str | None:
        post = Post.objects.filter(pk=post_pk).first() if post_pk else None
        return post.object_uri if post else None

    @staticmethod
    def delete_mark(mark):
        if mark.shelfmember and mark.shelfmember.post_id:
            Post.objects.filter(pk=mark.shelfmember.post_id).update(state="deleted")

    @staticmethod
    def post_mark(mark, share_as_new_post: bool):
        from catalog.common import ItemCategory
        from takahe.utils import Takahe

        user = mark.owner.user
        tags = (
            "\n"
            + user.preference.mastodon_append_tag.replace(
                "[category]", str(ItemCategory(mark.item.category).label)
            )
            if user.preference.mastodon_append_tag
            else ""
        )
        stars = _rating_to_emoji(mark.rating_grade, 0)
        item_link = f"{settings.SITE_INFO['site_url']}/~neodb~{mark.item.url}"

        pre_conetent = (
            f'{mark.action_label}<a href="{item_link}">《{mark.item.display_title}》</a>'
        )
        content = f"{stars}\n{mark.comment_text or ''}{tags}"
        data = {
            "object": {
                "relatedWith": [mark.item.ap_object_ref, mark.shelfmember.ap_object]
            }
        }
        if mark.comment:
            data["object"]["relatedWith"].append(mark.comment.ap_object)
        if mark.rating:
            data["object"]["relatedWith"].append(mark.rating.ap_object)
        if mark.visibility == 1:
            v = Takahe.Visibilities.followers
        elif mark.visibility == 2:
            v = Takahe.Visibilities.mentioned
        elif user.preference.mastodon_publish_public:
            v = Takahe.Visibilities.public
        else:
            v = Takahe.Visibilities.unlisted
        post_pk = Takahe.post(
            mark.owner.pk,
            pre_conetent,
            content,
            v,
            data,
            None if share_as_new_post else mark.shelfmember.post_id,
            mark.shelfmember.created_time,
        )
        if post_pk != mark.shelfmember.post_id:
            mark.shelfmember.post_id = post_pk
            mark.shelfmember.save(update_fields=["post_id"])
        if mark.comment and post_pk != mark.comment.post_id:
            mark.comment.post_id = post_pk
            mark.comment.save(update_fields=["post_id"])
        if mark.rating and post_pk != mark.rating.post_id:
            mark.rating.post_id = post_pk
            mark.rating.save(update_fields=["post_id"])

    @staticmethod
    def interact_post(post_pk: int, identity_pk: int, type: str):
        post = Post.objects.filter(pk=post_pk).first()
        if not post:
            logger.warning(f"Cannot find post {post_pk}")
            return
        interaction = PostInteraction.objects.get_or_create(
            type=type,
            identity_id=identity_pk,
            post=post,
        )[0]
        if interaction.state not in ["new", "fanned_out"]:
            interaction.state = "new"
            interaction.save()
        post.calculate_stats()
        return interaction

    @staticmethod
    def uninteract_post(post_pk: int, identity_pk: int, type: str):
        post = Post.objects.filter(pk=post_pk).first()
        if not post:
            logger.warning(f"Cannot find post {post_pk}")
            return
        for interaction in PostInteraction.objects.filter(
            type=type,
            identity_id=identity_pk,
            post=post,
        ):
            interaction.state = "undone"
            interaction.save()
        post.calculate_stats()

    @staticmethod
    def like_post(post_pk: int, identity_pk: int):
        return Takahe.interact_post(post_pk, identity_pk, "like")

    @staticmethod
    def unlike_post(post_pk: int, identity_pk: int):
        return Takahe.uninteract_post(post_pk, identity_pk, "like")

    @staticmethod
    def post_liked_by(post_pk: int, identity_pk: int) -> bool:
        interaction = Takahe.get_user_interaction(post_pk, identity_pk, "like")
        return interaction is not None and interaction.state in ["new", "fanned_out"]

    @staticmethod
    def get_user_interaction(post_pk: int, identity_pk: int, type: str):
        post = Post.objects.filter(pk=post_pk).first()
        if not post:
            logger.warning(f"Cannot find post {post_pk}")
            return None
        return PostInteraction.objects.filter(
            type=type,
            identity_id=identity_pk,
            post=post,
        ).first()

    @staticmethod
    def get_post_stats(post_pk: int) -> dict:
        post = Post.objects.filter(pk=post_pk).first()
        if not post:
            logger.warning(f"Cannot find post {post_pk}")
            return {}
        return post.stats or {}
