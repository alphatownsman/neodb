from unittest.mock import patch

import pytest
from django.template.loader import render_to_string
from django.test import Client

from catalog.models import Edition
from journal.models import Article, Note
from takahe.utils import Takahe
from users.models import User


def _fake_translate(text: str, lang: str, src: str | None) -> str:
    return f"T[{text}]" if text.strip() else text


@pytest.mark.django_db(databases="__all__")
class TestPostTranslate:
    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.author = User.register(email="tr_author@test.com", username="tr_author")
        self.viewer = User.register(email="tr_viewer@test.com", username="tr_viewer")
        self.client = Client()
        self.client.force_login(self.viewer, backend="mastodon.auth.OAuth2Backend")
        with (
            patch("journal.views.post.translate", side_effect=_fake_translate),
            patch("journal.views.article.translate", side_effect=_fake_translate),
        ):
            yield

    def _translate(self, post_id: int, query: str = "") -> str:
        response = self.client.post(f"/post/{post_id}/translate{query}")
        assert response.status_code == 200
        return response.content.decode()

    def test_plain_post_translates_content_warning(self):
        post = Takahe.post(
            self.author.identity.pk,
            "hello",
            Takahe.Visibilities.public,
            summary="spoiler ahead",
        )
        assert post
        html = self._translate(post.pk)
        assert "T[" in html and "hello" in html
        assert (
            f'<div hx-swap-oob="innerHTML" id="post_{post.pk}_summary">T[spoiler ahead]</div>'
            in html
        )

    def test_plain_post_without_summary_has_no_oob(self):
        post = Takahe.post(self.author.identity.pk, "hello", Takahe.Visibilities.public)
        assert post
        assert "hx-swap-oob" not in self._translate(post.pk)

    def test_note_keeps_quote_and_translates_title(self):
        book = Edition.objects.create(title="Translate Test Book")
        note = Note.objects.create(
            owner=self.author.identity,
            item=book,
            title="note title",
            content="note body",
            visibility=0,
        )
        assert note.latest_post_id
        html = self._translate(note.latest_post_id)
        assert html.startswith('<blockquote class="note-quote">T[')
        assert "note body" in html
        assert f'id="post_{note.latest_post_id}_summary">T[note title]</div>' in html

    def test_local_article_translates_teaser_not_body(self):
        article = Article.update_local_article(
            owner=self.author.identity,
            title="Long Form",
            body="Body content",
            summary="Short summary",
            visibility=0,
        )
        assert article.latest_post_id
        html = self._translate(article.latest_post_id)
        assert 'class="article-teaser"' in html
        assert "T[Long Form]" in html
        assert "T[Short summary]" in html
        assert "Body content" not in html

    def test_remote_article_teaser_and_full(self):
        post = Takahe.post(
            self.author.identity.pk,
            "Remote body",
            Takahe.Visibilities.public,
            data={"object": {"name": "Remote Title", "summary": "Remote summary"}},
            post_type="Article",
        )
        assert post
        teaser = self._translate(post.pk)
        assert 'class="article-teaser"' in teaser
        assert "T[Remote Title]" in teaser
        assert "T[Remote summary]" in teaser
        assert "Remote body" not in teaser
        full = self._translate(post.pk, "?full=1")
        assert 'class="remote-article"' in full
        assert "T[Remote Title]" in full
        assert "T[Remote summary]" in full
        assert "T[<p>Remote body</p>]" in full

    def test_remote_article_teaser_falls_back_to_body_text(self):
        post = Takahe.post(
            self.author.identity.pk,
            "Remote body",
            Takahe.Visibilities.public,
            data={"object": {"name": "Remote Title"}},
            post_type="Article",
        )
        assert post
        assert "T[Remote body]" in self._translate(post.pk)

    def test_article_page_translates_summary(self):
        article = Article.update_local_article(
            owner=self.author.identity,
            title="Long Form",
            body="Body content",
            summary="Short summary",
            visibility=0,
        )
        response = self.client.post(f"/article/translate/{article.uuid}")
        assert response.status_code == 200
        html = response.content.decode()
        assert f'id="article_{article.uuid}_title">T[Long Form]</span>' in html
        assert f'id="article_{article.uuid}_summary">T[Short summary]</span>' in html

    @pytest.mark.parametrize("show_full", [False, True])
    def test_remote_article_teaser_renders_without_name_or_summary(
        self, show_full: bool
    ):
        post = Takahe.post(
            self.author.identity.pk,
            "Remote body",
            Takahe.Visibilities.public,
            data={"object": {}},
            post_type="Article",
        )
        assert post
        html = render_to_string(
            "_remote_article_teaser.html", {"post": post, "show_full": show_full}
        )
        assert "Remote body" in html
