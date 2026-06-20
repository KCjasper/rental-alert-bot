from datetime import UTC, datetime, timedelta
from pathlib import Path

from rental_alert_bot.database import Database
from rental_alert_bot.listing import RentalListing, RentalSearchPage
from rental_alert_bot.monitoring_service import MonitoringService, MonitoringSettings
from rental_alert_bot.rental_parser import RentalPageBlockedError
from rental_alert_bot.repository import RentalRepository, Subscription
from rental_alert_bot.telegram_client import TelegramApiError

NOW = datetime(2026, 6, 20, 9, 0, tzinfo=UTC)
CHAT_ID = 123456


class FakeTelegram:
    def __init__(
        self,
        *,
        fail_after: int | None = None,
        fail_photos: bool = False,
    ) -> None:
        self.sent_messages: list[tuple[int, str]] = []
        self.sent_photos: list[tuple[int, str, str]] = []
        self.fail_after = fail_after
        self.fail_photos = fail_photos

    def send_message(self, chat_id: int, text: str) -> None:
        if self.fail_after is not None and len(self.sent_messages) >= self.fail_after:
            raise TelegramApiError("telegram failed", error_code=500)
        self.sent_messages.append((chat_id, text))

    def send_photo(self, chat_id: int, photo_url: str, caption: str) -> None:
        if self.fail_photos:
            raise TelegramApiError("telegram photo failed", error_code=400)
        self.sent_photos.append((chat_id, photo_url, caption))

    @property
    def texts(self) -> list[str]:
        return [text for _chat_id, text in self.sent_messages]


class FakeRentalFetcher:
    def __init__(
        self,
        pages: list[RentalSearchPage] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.pages = pages or [RentalSearchPage(total_count=1, listings=(listing("90000001"),))]
        self.error = error
        self.fetched_urls: list[str] = []

    def fetch(self, raw_url: str) -> RentalSearchPage:
        self.fetched_urls.append(raw_url)
        if self.error is not None:
            raise self.error
        return self.pages[min(len(self.fetched_urls) - 1, len(self.pages) - 1)]


class SequenceRentalFetcher:
    def __init__(self, results: list[RentalSearchPage | Exception]) -> None:
        self.results = results
        self.fetched_urls: list[str] = []

    def fetch(self, raw_url: str) -> RentalSearchPage:
        self.fetched_urls.append(raw_url)
        result = self.results[min(len(self.fetched_urls) - 1, len(self.results) - 1)]
        if isinstance(result, Exception):
            raise result
        return result


def listing(listing_id: str, *, image_url: str | None = None) -> RentalListing:
    return RentalListing(
        listing_id=listing_id,
        url=f"https://rent.591.com.tw/{listing_id}",
        title=f"測試房源 {listing_id}",
        price_monthly=18_500,
        location="中山區-測試路",
        category="獨立套房",
        layout="1房1廳",
        area_ping=8.5,
        floor="3F/5F",
        published_text="3分鐘內更新",
        image_url=image_url,
    )


def repository(path: Path) -> RentalRepository:
    database = Database(path)
    database.initialize()
    return RentalRepository(database, clock=lambda: NOW)


def active_subscription(repo: RentalRepository, *, region: int = 1) -> Subscription:
    subscription = repo.create_subscription(
        name="台北測試",
        source_url=f"https://rent.591.com.tw/list?region={region}",
        normalized_url=f"https://rent.591.com.tw/list?region={region}&sort=posttime",
    )
    return repo.activate_subscription(subscription.id)


def service(
    repo: RentalRepository,
    telegram: FakeTelegram | None = None,
    fetcher: FakeRentalFetcher | None = None,
) -> MonitoringService:
    return MonitoringService(
        repository=repo,
        telegram=telegram or FakeTelegram(),
        rental_fetcher=fetcher or FakeRentalFetcher(),
        settings=MonitoringSettings(
            alert_chat_id=CHAT_ID,
            poll_interval_seconds=300,
            poll_jitter_seconds=30,
            failure_alert_threshold=2,
        ),
        clock=lambda: NOW,
        random_integer=lambda _start, _end: 7,
    )


def test_due_subscription_check_sends_new_listing_once(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = active_subscription(repo)
    telegram = FakeTelegram()
    monitor = service(repo, telegram)

    first = monitor.check_due_subscriptions()
    second = monitor.check_due_subscriptions()

    assert [result.subscription_id for result in first] == [subscription.id]
    assert first[0].discovered_count == 1
    assert first[0].sent_count == 1
    assert second == ()
    assert len(telegram.sent_messages) == 1
    assert "新房源：測試房源 90000001" in telegram.texts[0]
    runs = repo.list_monitor_runs()
    assert len(runs) == 2
    assert runs[0].checked_count == 1
    assert runs[0].succeeded_count == 1
    assert runs[0].sent_count == 1
    assert runs[1].checked_count == 0

    updated = repo.get_subscription(subscription.id)
    assert updated.last_success_at == NOW
    assert updated.last_result_count == 1
    assert updated.next_check_at == NOW + timedelta(seconds=307)


def test_listing_with_image_is_sent_as_photo(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = active_subscription(repo)
    telegram = FakeTelegram()
    fetcher = FakeRentalFetcher(
        [
            RentalSearchPage(
                total_count=1,
                listings=(
                    listing(
                        "90000001",
                        image_url="https://hp1.591.com.tw/house.jpg",
                    ),
                ),
            )
        ]
    )
    monitor = service(repo, telegram, fetcher)

    result = monitor.check_subscription(subscription)

    assert result.sent_count == 1
    assert telegram.sent_messages == []
    assert telegram.sent_photos[0][1] == "https://hp1.591.com.tw/house.jpg"
    assert "新房源：測試房源 90000001" in telegram.sent_photos[0][2]
    assert repo.list_pending_notifications(subscription.id) == ()


def test_image_send_failure_falls_back_to_text_notification(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = active_subscription(repo)
    telegram = FakeTelegram(fail_photos=True)
    fetcher = FakeRentalFetcher(
        [
            RentalSearchPage(
                total_count=1,
                listings=(
                    listing(
                        "90000001",
                        image_url="https://hp1.591.com.tw/house.jpg",
                    ),
                ),
            )
        ]
    )
    monitor = service(repo, telegram, fetcher)

    result = monitor.check_subscription(subscription)

    assert result.sent_count == 1
    assert telegram.sent_photos == []
    assert "新房源：測試房源 90000001" in telegram.texts[0]
    assert repo.list_pending_notifications(subscription.id) == ()
    assert repo.notification_event_count(subscription.id, "90000001", status="failed") == 1
    assert repo.notification_event_count(subscription.id, "90000001", status="sent") == 1


def test_check_due_subscriptions_skips_not_due_and_non_active(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    active = active_subscription(repo)
    repo.record_check(
        active.id,
        result_count=1,
        succeeded=True,
        next_check_at=NOW + timedelta(minutes=5),
    )
    paused = active_subscription(repo, region=3)
    repo.pause_subscription(paused.id)

    monitor = service(repo)

    assert monitor.check_due_subscriptions() == ()
    runs = repo.list_monitor_runs()
    assert len(runs) == 1
    assert runs[0].checked_count == 0


def test_telegram_failure_leaves_listing_pending_for_retry(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = active_subscription(repo)
    telegram = FakeTelegram(fail_after=0)
    monitor = service(repo, telegram)

    result = monitor.check_subscription(subscription)

    assert result.sent_count == 0
    assert result.failed_count == 1
    pending = repo.list_pending_notifications(subscription.id)
    assert [item.listing.listing_id for item in pending] == ["90000001"]
    assert pending[0].attempt_count == 1


def test_repeated_591_failures_record_check_and_send_alert(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = active_subscription(repo)
    telegram = FakeTelegram()
    monitor = service(
        repo,
        telegram,
        FakeRentalFetcher(error=RentalPageBlockedError("blocked by verification")),
    )

    first = monitor.check_subscription(subscription)
    second = monitor.check_subscription(subscription)
    third = monitor.check_subscription(subscription)

    assert first.succeeded is False
    assert second.succeeded is False
    assert third.succeeded is False
    assert repo.get_subscription(subscription.id).last_success_at is None
    assert repo.get_subscription(subscription.id).next_check_at == NOW + timedelta(seconds=307)
    assert len(telegram.sent_messages) == 1
    assert "系統告警" in telegram.texts[0]


def test_591_failure_recovery_sends_single_recovery_notification(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = active_subscription(repo)
    telegram = FakeTelegram()
    blocked = RentalPageBlockedError("blocked by verification")
    monitor = service(
        repo,
        telegram,
        SequenceRentalFetcher(
            [
                blocked,
                blocked,
                RentalSearchPage(total_count=1, listings=(listing("90000001"),)),
                RentalSearchPage(total_count=1, listings=(listing("90000001"),)),
            ]
        ),
    )

    assert monitor.check_subscription(subscription).succeeded is False
    assert monitor.check_subscription(subscription).succeeded is False
    recovered = monitor.check_subscription(subscription)
    still_healthy = monitor.check_subscription(subscription)

    assert recovered.succeeded is True
    assert still_healthy.succeeded is True
    assert sum("系統告警" in text for text in telegram.texts) == 1
    assert sum("已恢復" in text for text in telegram.texts) == 1
    assert "先前連續失敗次數：2" in telegram.texts[1]


def test_failure_alert_send_error_does_not_fail_subscription_check(
    tmp_path: Path,
) -> None:
    repo = repository(tmp_path / "rental.db")
    subscription = active_subscription(repo)
    telegram = FakeTelegram(fail_after=0)
    monitor = service(
        repo,
        telegram,
        FakeRentalFetcher(error=RentalPageBlockedError("blocked by verification")),
    )

    first = monitor.check_subscription(subscription)
    second = monitor.check_subscription(subscription)

    assert first.succeeded is False
    assert second.succeeded is False
    assert telegram.sent_messages == []


def test_due_subscription_failure_is_counted_in_monitor_run(tmp_path: Path) -> None:
    repo = repository(tmp_path / "rental.db")
    active_subscription(repo)
    monitor = service(
        repo,
        fetcher=FakeRentalFetcher(error=RentalPageBlockedError("blocked by verification")),
    )

    result = monitor.check_due_subscriptions()

    assert result[0].succeeded is False
    runs = repo.list_monitor_runs()
    assert len(runs) == 1
    assert runs[0].checked_count == 1
    assert runs[0].succeeded_count == 0
    assert runs[0].failed_count == 1
    assert runs[0].status == "completed"
