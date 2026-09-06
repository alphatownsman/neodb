import uuid
from datetime import datetime
from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from ninja import Field, Schema, Status
from ninja.pagination import paginate

from catalog.models import ItemSchema
from common.api import (
    NOT_FOUND,
    OK,
    PageNumberPagination,
    RedirectedResult,
    Result,
    api,
    resolve_item_for_read,
    resolve_item_for_write,
)
from common.sentry import record_activity
from takahe.utils import Takahe
from users.apis import UserIdentitySchema

from ..models import Attachment, Note

# takahe re-encodes a thumbnail in memory when it takes an upload, and refuses
# anything past this. Our own upload endpoint allows more, so a file can be
# registered here and still be too big to post.
MAX_POST_ATTACHMENT_SIZE = 5 * 1024 * 1024
# Mastodon's per-status limit, which the web composer already follows.
MAX_ATTACHMENTS_PER_NOTE = 4


def _attachment_json(attachment: Any) -> dict[str, Any]:
    """One attachment as wire JSON, from a registry row or a legacy entry.

    Both shapes share the four keys of ``Attachment.to_json``; a row adds the
    ones the legacy JSON never carried.
    """
    if isinstance(attachment, dict):
        return {
            "uuid": None,
            "type": attachment.get("type") or "unknown",
            "mimetype": attachment.get("mimetype") or "",
            "url": attachment.get("url") or "",
            "preview_url": attachment.get("preview_url") or "",
        }
    return {
        **attachment.to_json(),
        "uuid": attachment.uuid,
        "description": attachment.description,
        "width": attachment.width,
        "height": attachment.height,
    }


def _resolve_attachments(
    identity, uuids: list[str]
) -> "tuple[list[Attachment] | None, str]":
    """Owned rows for ``uuids``, in the order given, or ``(None, reason)``.

    Every rejection is the caller's to fix, so each one names what is wrong
    rather than silently dropping the attachment from the note.
    """
    if len(uuids) > MAX_ATTACHMENTS_PER_NOTE:
        return None, f"At most {MAX_ATTACHMENTS_PER_NOTE} attachments per note"
    rows: list[Attachment] = []
    for u in uuids:
        try:
            uid = uuid.UUID(u)
        except ValueError:
            return None, f"Invalid attachment: {u}"
        # scoped to the caller: an id belonging to someone else must not be
        # distinguishable from one that does not exist
        attachment = Attachment.objects.filter(owner=identity, uid=uid).first()
        if not attachment:
            return None, f"Attachment not found: {u}"
        if not attachment.file:
            # a pointer row for remote media; we hold URLs, not bytes
            return None, f"Attachment has no file to post: {u}"
        if attachment.size > MAX_POST_ATTACHMENT_SIZE:
            return None, f"Attachment too large to post: {u}"
        rows.append(attachment)
    return rows, ""


class NoteAttachmentSchema(Schema):
    """One piece of media on a note.

    Notes carry media in two shapes: registry rows, and the legacy JSON of
    notes the backfill has not reached. Both are normalized to this, so a
    client never has to tell them apart. `uuid` is null for a legacy entry,
    which is what says the file is not addressable through
    `/api/me/attachment/`.
    """

    uuid: str | None = None
    type: str
    mimetype: str = ""
    url: str
    preview_url: str = ""
    description: str = ""
    width: int | None = None
    height: int | None = None


class NoteSchema(Schema):
    uuid: str
    # No url/id here: a note has no page of its own, so it keeps the `Piece`
    # default url_path and Piece.url/absolute_url point at nothing.
    api_url: str
    post_id: int | None = Field(alias="latest_post_id")
    item: ItemSchema
    owner: UserIdentitySchema
    title: str | None
    content: str
    sensitive: bool = False
    progress_type: Note.ProgressType | None = None
    progress_value: str | None = None
    visibility: int = Field(ge=0, le=2)
    created_time: datetime
    attachments: list[NoteAttachmentSchema] = []

    @staticmethod
    def resolve_api_url(obj: Note) -> str:
        # the owner-scoped route is the one that resolves (PUT / DELETE)
        return f"/api/me/note/{obj.uuid}"

    @staticmethod
    def resolve_attachments(obj: Note) -> list[dict[str, Any]]:
        return [_attachment_json(a) for a in obj.attachment_list]


class NoteInSchema(Schema):
    title: str
    content: str
    sensitive: bool = False
    progress_type: Note.ProgressType | None = None
    progress_value: str | None = None
    visibility: int = Field(ge=0, le=2)
    post_to_fediverse: bool = False
    # Tri-state on purpose: omitted leaves existing media alone, so a client
    # written before this field cannot wipe the media on the notes it edits.
    # An empty list is the explicit "remove all media".
    attachment_uuids: list[str] | None = None


class NotePageNumberPagination(PageNumberPagination):
    """Pagination that batch-loads takahe identities after slicing.

    ``select_related("owner")`` hands each row its own ``APIdentity``, so
    ``NoteSchema.owner`` would resolve display_name/avatar with one cross-db
    lookup per row.
    """

    def paginate_queryset(
        self,
        queryset: QuerySet,
        pagination: PageNumberPagination.Input,
        request: HttpRequest,
        **params: Any,
    ):
        val = super().paginate_queryset(queryset, pagination, request, **params)
        data = val.get("data")
        if data:
            Takahe.prefetch_takahe_identities([n.owner for n in data])
        return val


@api.get(
    "/me/note/item/{item_uuid}/",
    response={
        200: list[NoteSchema],
        302: RedirectedResult,
        401: Result,
        403: Result,
        404: Result,
    },
    tags=["note"],
)
@paginate(NotePageNumberPagination)
def list_notes_for_item(request, item_uuid: str, response: HttpResponse):
    """
    List notes by current user for an item

    If the item was merged into another one, HTTP 302 is returned.
    """
    item, redirect = resolve_item_for_read(
        item_uuid, "/api/me/note/item/{uuid}/", response
    )
    if not item:
        return redirect
    queryset = Note.objects.filter(
        owner=request.user.identity, item=item
    ).select_related("owner")
    # attachment_records feeds NoteSchema.attachments, which would otherwise
    # be one query per note
    return queryset.prefetch_related("item", "attachment_records")


@api.post(
    "/me/note/item/{item_uuid}/",
    response={
        200: NoteSchema,
        307: RedirectedResult,
        400: Result,
        401: Result,
        403: Result,
        404: Result,
    },
    tags=["note"],
)
def add_note_for_item(
    request, item_uuid: str, n_in: NoteInSchema, response: HttpResponse
):
    """
    Add a note for an item

    If the item was merged into another one, HTTP 307 is returned; repeat the
    request against the returned url.

    To attach media, upload it to `/api/me/attachment/` first and pass the
    returned uuids as `attachment_uuids`. They must be your own uploads, at
    most 4, each no larger than 5MB. They become the media of the federated
    post as well, so other servers see the same images.
    """
    item, redirect = resolve_item_for_write(
        item_uuid, "/api/me/note/item/{uuid}/", response
    )
    if not item:
        return redirect
    attachments = None
    if n_in.attachment_uuids is not None:
        attachments, error = _resolve_attachments(
            request.user.identity, n_in.attachment_uuids
        )
        if attachments is None:
            return Status(400, {"message": error})
    note = Note()
    note.item = item
    note.owner = request.user.identity
    note.title = n_in.title
    note.content = n_in.content
    note.sensitive = n_in.sensitive
    note.progress_type = n_in.progress_type
    note.progress_value = n_in.progress_value
    note.visibility = n_in.visibility
    note.crosspost_when_save = n_in.post_to_fediverse
    note.application_id_when_save = getattr(request, "application_id", None)
    if attachments is not None:
        note.set_attachments(attachments)
    note.save()
    record_activity("note", "api")
    return note


@api.put(
    "/me/note/{note_uuid}",
    response={200: NoteSchema, 400: Result, 401: Result, 403: Result, 404: Result},
    tags=["note"],
)
def update_note(request, note_uuid: str, n_in: NoteInSchema):
    """
    Update a note.

    `attachment_uuids` replaces the note's media, and an empty list removes
    it. Leave the field out to keep the media as it is, which is what an
    edit of a note composed in a Mastodon client should do.
    """
    note = Note.get_by_url_and_owner(note_uuid, request.user.identity.pk)
    if not note:
        return NOT_FOUND
    if n_in.attachment_uuids is not None:
        attachments, error = _resolve_attachments(
            request.user.identity, n_in.attachment_uuids
        )
        if attachments is None:
            return Status(400, {"message": error})
        note.set_attachments(attachments)
    note.title = n_in.title
    note.content = n_in.content
    note.sensitive = n_in.sensitive
    note.progress_type = n_in.progress_type
    note.progress_value = n_in.progress_value
    note.visibility = n_in.visibility
    note.crosspost_when_save = n_in.post_to_fediverse
    note.application_id_when_save = getattr(request, "application_id", None)
    note.save()
    record_activity("note", "api")
    return note


@api.delete(
    "/me/note/{note_uuid}",
    response={200: Result, 401: Result, 403: Result, 404: Result},
    tags=["note"],
)
def delete_note(request, note_uuid: str):
    """
    Delete a note.
    """
    note = Note.get_by_url_and_owner(note_uuid, request.user.identity.pk)
    if not note:
        return NOT_FOUND
    note.delete()
    return OK
