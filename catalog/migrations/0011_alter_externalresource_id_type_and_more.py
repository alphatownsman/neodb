# Generated by Django 4.2.3 on 2023-08-06 02:01

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0011_remove_item_last_editor"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externalresource",
            name="id_type",
            field=models.CharField(
                choices=[
                    ("wikidata", "维基数据"),
                    ("isbn10", "ISBN10"),
                    ("isbn", "ISBN"),
                    ("asin", "ASIN"),
                    ("issn", "ISSN"),
                    ("cubn", "统一书号"),
                    ("isrc", "ISRC"),
                    ("gtin", "GTIN UPC EAN码"),
                    ("rss", "RSS Feed URL"),
                    ("imdb", "IMDb"),
                    ("tmdb_tv", "TMDB剧集"),
                    ("tmdb_tvseason", "TMDB剧集"),
                    ("tmdb_tvepisode", "TMDB剧集"),
                    ("tmdb_movie", "TMDB电影"),
                    ("goodreads", "Goodreads"),
                    ("goodreads_work", "Goodreads著作"),
                    ("googlebooks", "谷歌图书"),
                    ("doubanbook", "豆瓣读书"),
                    ("doubanbook_work", "豆瓣读书著作"),
                    ("doubanmovie", "豆瓣电影"),
                    ("doubanmusic", "豆瓣音乐"),
                    ("doubangame", "豆瓣游戏"),
                    ("doubandrama", "豆瓣舞台剧"),
                    ("doubandrama_version", "豆瓣舞台剧版本"),
                    ("bookstw", "博客来图书"),
                    ("bandcamp", "Bandcamp"),
                    ("spotify_album", "Spotify专辑"),
                    ("spotify_show", "Spotify播客"),
                    ("discogs_release", "Discogs Release"),
                    ("discogs_master", "Discogs Master"),
                    ("musicbrainz", "MusicBrainz ID"),
                    ("doubanbook_author", "豆瓣读书作者"),
                    ("doubanmovie_celebrity", "豆瓣电影影人"),
                    ("goodreads_author", "Goodreads作者"),
                    ("spotify_artist", "Spotify艺术家"),
                    ("tmdb_person", "TMDB影人"),
                    ("igdb", "IGDB游戏"),
                    ("steam", "Steam游戏"),
                    ("bangumi", "Bangumi"),
                    ("apple_podcast", "苹果播客"),
                    ("apple_music", "苹果音乐"),
                    ("fedi", "联邦实例"),
                ],
                max_length=50,
                verbose_name="IdType of the source site",
            ),
        ),
        migrations.AlterField(
            model_name="itemlookupid",
            name="id_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("wikidata", "维基数据"),
                    ("isbn10", "ISBN10"),
                    ("isbn", "ISBN"),
                    ("asin", "ASIN"),
                    ("issn", "ISSN"),
                    ("cubn", "统一书号"),
                    ("isrc", "ISRC"),
                    ("gtin", "GTIN UPC EAN码"),
                    ("rss", "RSS Feed URL"),
                    ("imdb", "IMDb"),
                    ("tmdb_tv", "TMDB剧集"),
                    ("tmdb_tvseason", "TMDB剧集"),
                    ("tmdb_tvepisode", "TMDB剧集"),
                    ("tmdb_movie", "TMDB电影"),
                    ("goodreads", "Goodreads"),
                    ("goodreads_work", "Goodreads著作"),
                    ("googlebooks", "谷歌图书"),
                    ("doubanbook", "豆瓣读书"),
                    ("doubanbook_work", "豆瓣读书著作"),
                    ("doubanmovie", "豆瓣电影"),
                    ("doubanmusic", "豆瓣音乐"),
                    ("doubangame", "豆瓣游戏"),
                    ("doubandrama", "豆瓣舞台剧"),
                    ("doubandrama_version", "豆瓣舞台剧版本"),
                    ("bookstw", "博客来图书"),
                    ("bandcamp", "Bandcamp"),
                    ("spotify_album", "Spotify专辑"),
                    ("spotify_show", "Spotify播客"),
                    ("discogs_release", "Discogs Release"),
                    ("discogs_master", "Discogs Master"),
                    ("musicbrainz", "MusicBrainz ID"),
                    ("doubanbook_author", "豆瓣读书作者"),
                    ("doubanmovie_celebrity", "豆瓣电影影人"),
                    ("goodreads_author", "Goodreads作者"),
                    ("spotify_artist", "Spotify艺术家"),
                    ("tmdb_person", "TMDB影人"),
                    ("igdb", "IGDB游戏"),
                    ("steam", "Steam游戏"),
                    ("bangumi", "Bangumi"),
                    ("apple_podcast", "苹果播客"),
                    ("apple_music", "苹果音乐"),
                    ("fedi", "联邦实例"),
                ],
                max_length=50,
                verbose_name="源网站",
            ),
        ),
    ]
