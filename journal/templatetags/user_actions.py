from django import template
from django.urls import reverse

from journal.models import Collection, Like
from takahe.utils import Takahe

register = template.Library()


@register.simple_tag(takes_context=True)
def wish_item_action(context, item):
    user = context["request"].user
    action = {}
    if user and user.is_authenticated:
        action = {
            "taken": user.shelf_manager.locate_item(item) is not None,
            "url": reverse("journal:wish", args=[item.uuid]),
        }
    return action


@register.simple_tag(takes_context=True)
def like_piece_action(context, piece):
    user = context["request"].user
    action = {}
    if user and user.is_authenticated and piece and piece.post_id:
        action = {
            "taken": Takahe.post_liked_by(piece.post_id, user),
            "url": reverse("journal:like", args=[piece.uuid]),
        }
    return action


@register.simple_tag(takes_context=True)
def liked_piece(context, piece):
    user = context["request"].user
    return (
        user
        and user.is_authenticated
        and piece.post_id
        and Takahe.get_user_interaction(piece.post_id, user, "like")
    )
