from datetime import UTC, datetime
from pathlib import Path

from rental_alert_bot.bot_service import BotService, BotServiceSettings
from rental_alert_bot.database import Database
from rental_alert_bot.listing import RentalListing, RentalSearchPage
from rental_alert_bot.repository import RentalRepository, SubscriptionStatus
from rental_alert_bot.telegram_models import TelegramUpdate

AUTHORIZED_USER_ID = 123456
UNAUTHORIZED_USER_ID = 999999
CHAT_ID = 777
NOW = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)


class FakeTelegram:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))

    @property
    def texts(self) -> list[str]:
        return [text for _chat_id, text in self.sent_messages]


class FakeRentalFetcher:
    def __init__(self, page: RentalSearchPage | None = None) -> None:
        self.page = page or RentalSearchPage(total_count=2, listings=(listing("90000001"),))
        self.fetched_urls: list[str] = []

    def fetch(self, raw_url: str) -> RentalSearchPage:
        self.fetched_urls.append(raw_url)
        return self.page


def listing(listing_id: str) -> RentalListing:
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
    )


def update(text: str, *, user_id: int = AUTHORIZED_USER_ID) -> TelegramUpdate:
    return TelegramUpdate.from_api(
        {
            "update_id": 1,
            "message": {
                "message_id": 2,
                "chat": {"id": CHAT_ID, "type": "private"},
                "from": {"id": user_id, "is_bot": False, "first_name": "KC"},
                "text": text,
            },
        }
    )


def service(tmp_path: Path, fetcher: FakeRentalFetcher | None = None):
    database = Database(tmp_path / "rental.db")
    database.initialize()
    repo = RentalRepository(database, clock=lambda: NOW)
    telegram = FakeTelegram()
    rental_fetcher = fetcher or FakeRentalFetcher()
    bot = BotService(
        repository=repo,
        telegram=telegram,
        rental_fetcher=rental_fetcher,
        settings=BotServiceSettings(
            authorized_user_id=AUTHORIZED_USER_ID,
            initial_notification_batch_size=1,
            send_delay_seconds=0,
        ),
        sleep=lambda _delay: None,
        clock=lambda: NOW,
    )
    return bot, repo, telegram, rental_fetcher


def create_active_subscription(repo: RentalRepository) -> int:
    subscription = repo.create_subscription(
        name="台北測試",
        source_url="https://rent.591.com.tw/list?region=1",
        normalized_url="https://rent.591.com.tw/list?region=1&sort=posttime",
    )
    repo.activate_subscription(subscription.id)
    return subscription.id


def test_rejects_unauthorized_user_without_touching_data(tmp_path: Path) -> None:
    bot, repo, telegram, fetcher = service(tmp_path)

    bot.handle_update(
        update("https://rent.591.com.tw/list?region=1", user_id=UNAUTHORIZED_USER_ID)
    )

    assert repo.list_subscriptions() == ()
    assert fetcher.fetched_urls == []
    assert "沒有操作權限" in telegram.texts[-1]
    events = repo.list_bot_command_events()
    assert events[-1].command == "url"
    assert events[-1].authorized is False
    assert events[-1].status == "rejected"


def test_start_and_help_send_usage_text(tmp_path: Path) -> None:
    bot, repo, telegram, _fetcher = service(tmp_path)

    bot.handle_update(update("/start"))
    bot.handle_update(update("/help"))

    assert all("/subscriptions" in text for text in telegram.texts)
    assert [event.command for event in repo.list_bot_command_events()] == [
        "/start",
        "/help",
    ]


def test_url_creates_pending_subscription_then_confirm_sends_initial_listings(
    tmp_path: Path,
) -> None:
    page = RentalSearchPage(
        total_count=30,
        listings=(listing("90000001"), listing("90000002")),
    )
    bot, repo, telegram, _fetcher = service(tmp_path, FakeRentalFetcher(page))

    bot.handle_update(update("https://rent.591.com.tw/list?region=1&utm_source=x"))
    subscription = repo.list_subscriptions()[0]
    assert subscription.status is SubscriptionStatus.PENDING
    assert repo.find_latest_pending_action() is not None
    assert "目前 591 顯示約 30 筆" in telegram.texts[-1]

    bot.handle_update(update("確認"))

    assert repo.get_subscription(subscription.id).status is SubscriptionStatus.ACTIVE
    assert repo.list_pending_notifications(subscription.id) == ()
    assert any("新房源：測試房源 90000001" in text for text in telegram.texts)
    assert any("首次全量通知完成，共發送 2 筆" in text for text in telegram.texts)
    assert [event.command for event in repo.list_bot_command_events()] == ["url", "confirm"]


def test_cancel_pending_initial_subscription_soft_deletes_it(tmp_path: Path) -> None:
    bot, repo, telegram, _fetcher = service(tmp_path)
    bot.handle_update(update("https://rent.591.com.tw/list?region=1"))
    subscription = repo.list_subscriptions()[0]

    bot.handle_update(update("/cancel"))

    assert repo.list_subscriptions() == ()
    assert repo.get_subscription(subscription.id).status is SubscriptionStatus.DELETED
    assert "已取消" in telegram.texts[-1]
    assert [event.command for event in repo.list_bot_command_events()] == ["url", "/cancel"]


def test_subscriptions_pause_resume_and_delete_confirmation(tmp_path: Path) -> None:
    bot, repo, telegram, _fetcher = service(tmp_path)
    subscription_id = create_active_subscription(repo)

    bot.handle_update(update("/subscriptions"))
    assert f"#{subscription_id}" in telegram.texts[-1]

    bot.handle_update(update(f"/pause {subscription_id}"))
    assert repo.get_subscription(subscription_id).status is SubscriptionStatus.PAUSED

    bot.handle_update(update(f"/resume {subscription_id}"))
    assert repo.get_subscription(subscription_id).status is SubscriptionStatus.ACTIVE

    bot.handle_update(update(f"/delete {subscription_id}"))
    assert "請回覆「確認」" in telegram.texts[-1]
    bot.handle_update(update("確認"))
    assert repo.get_subscription(subscription_id).status is SubscriptionStatus.DELETED


def test_test_command_fetches_without_changing_dedup_state(tmp_path: Path) -> None:
    page = RentalSearchPage(total_count=10, listings=(listing("90000001"),))
    bot, repo, telegram, fetcher = service(tmp_path, FakeRentalFetcher(page))
    subscription_id = create_active_subscription(repo)

    bot.handle_update(update(f"/test {subscription_id}"))

    assert fetcher.fetched_urls == ["https://rent.591.com.tw/list?region=1&sort=posttime"]
    assert repo.list_pending_notifications(subscription_id) == ()
    assert "不會改變已通知狀態" in telegram.texts[-1]


def test_invalid_command_arguments_return_clear_error(tmp_path: Path) -> None:
    bot, _repo, telegram, _fetcher = service(tmp_path)

    bot.handle_update(update("/pause abc"))

    assert "訂閱編號必須是數字" in telegram.texts[-1]


def test_unknown_text_is_rejected(tmp_path: Path) -> None:
    bot, _repo, telegram, _fetcher = service(tmp_path)

    bot.handle_update(update("hello"))

    assert "591 租屋搜尋網址" in telegram.texts[-1]


def test_short_share_url_returns_clear_error(tmp_path: Path) -> None:
    bot, repo, telegram, fetcher = service(tmp_path)

    bot.handle_update(update("https://591.to/2n5g"))

    assert repo.list_subscriptions() == ()
    assert fetcher.fetched_urls == []
    assert "短網址或分享連結目前不支援" in telegram.texts[-1]
    events = repo.list_bot_command_events()
    assert events[-1].command == "url"
    assert events[-1].status == "failed"
    assert events[-1].error_code == "rental_url_error"
