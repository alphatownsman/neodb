from django.core.management.base import BaseCommand
from django.core.cache import cache
import pprint
from catalog.models import *
from journal.models import ShelfMember, query_item_category, ItemCategory, Comment
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count


MAX_ITEMS_PER_PERIOD = 12
MIN_MARKS = 2
MAX_DAYS_FOR_PERIOD = 64
MIN_DAYS_FOR_PERIOD = 4


class Command(BaseCommand):
    help = "catalog app utilities"

    def add_arguments(self, parser):
        parser.add_argument(
            "--update",
            action="store_true",
            help="generate discover data",
        )

    def get_popular_marked_item_ids(self, category, days, exisiting_ids):
        item_ids = [
            m["item_id"]
            for m in ShelfMember.objects.filter(query_item_category(category))
            .filter(created_time__gt=timezone.now() - timedelta(days=days))
            .exclude(item_id__in=exisiting_ids)
            .values("item_id")
            .annotate(num=Count("item_id"))
            .filter(num__gte=MIN_MARKS)
            .order_by("-num")[:MAX_ITEMS_PER_PERIOD]
        ]
        return item_ids

    def get_popular_commented_item_ids(self, category, days, exisiting_ids):
        item_ids = [
            m["item_id"]
            for m in Comment.objects.filter(query_item_category(category))
            .filter(created_time__gt=timezone.now() - timedelta(days=days))
            .exclude(item_id__in=exisiting_ids)
            .values("item_id")
            .annotate(num=Count("item_id"))
            .filter(num__gte=MIN_MARKS)
            .order_by("-num")[:MAX_ITEMS_PER_PERIOD]
        ]
        return item_ids

    def cleanup_shows(self, items):
        seasons = [i for i in items if i.__class__ == TVSeason]
        for season in seasons:
            if season.show in items:
                items.remove(season.show)
        return items

    def handle(self, *args, **options):
        if options["update"]:
            cache_key = "public_gallery"
            gallery_categories = [
                ItemCategory.Book,
                ItemCategory.Movie,
                ItemCategory.TV,
                ItemCategory.Game,
                ItemCategory.Music,
                ItemCategory.Podcast,
            ]
            gallery_list = []
            for category in gallery_categories:
                days = MAX_DAYS_FOR_PERIOD
                item_ids = []
                while days >= MIN_DAYS_FOR_PERIOD:
                    ids = self.get_popular_marked_item_ids(category, days, item_ids)
                    self.stdout.write(
                        f"Marked {category} for last {days} days: {len(ids)}"
                    )
                    item_ids = ids + item_ids
                    days //= 2
                if category == ItemCategory.Podcast:
                    extra_ids = self.get_popular_commented_item_ids(
                        ItemCategory.Podcast, MAX_DAYS_FOR_PERIOD, item_ids
                    )
                    self.stdout.write(
                        f"Commented podcast for last {MAX_DAYS_FOR_PERIOD} days: {len(extra_ids)}"
                    )
                    item_ids = extra_ids + item_ids
                items = [Item.objects.get(pk=i) for i in item_ids]
                if category == ItemCategory.TV:
                    items = self.cleanup_shows(items)
                gallery_list.append(
                    {
                        "name": "popular_" + category.value,
                        "title": ""
                        + (category.label if category != ItemCategory.Book else "图书"),
                        "items": items,
                    }
                )
            cache.set(cache_key, gallery_list, timeout=None)
        self.stdout.write(self.style.SUCCESS(f"Done."))