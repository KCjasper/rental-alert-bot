"""Traditional Chinese Telegram message templates."""

from __future__ import annotations

from rental_alert_bot.listing import RentalListing
from rental_alert_bot.repository import Subscription

HELP_TEXT = """租屋情報機器人

把 591 租屋搜尋結果網址貼給我，我會先顯示目前房源數量。

可用指令：
/subscriptions 查看訂閱
/pause 暫停訂閱，我會再請你輸入編號
/resume 恢復訂閱，我會再請你輸入編號
/delete 刪除訂閱，我會再請你輸入編號並二次確認
/test 立即測試抓取，我會再請你輸入編號
/cancel 取消等待確認或等待輸入編號的動作
/help 顯示本說明

也可以直接輸入 /pause 1、/resume 1、/delete 1、/test 1。
"""


def unauthorized_message() -> str:
    return "此 Bot 僅供私人使用，這個帳號沒有操作權限。"


def subscription_created_message(subscription_id: int, total_count: int, parsed_count: int) -> str:
    return (
        f"已讀取搜尋條件 #{subscription_id}。\n"
        f"目前 591 顯示約 {total_count} 筆，這次可解析 {parsed_count} 筆。\n"
        "若要接收目前已存在的房源，請回覆「確認」。\n"
        "若不要建立，請輸入 /cancel。"
    )


def subscriptions_message(subscriptions: tuple[Subscription, ...]) -> str:
    if not subscriptions:
        return "目前沒有訂閱。請貼上 591 租屋搜尋結果網址建立第一組訂閱。"

    lines = ["目前訂閱："]
    for subscription in subscriptions:
        last_count = (
            f"{subscription.last_result_count} 筆"
            if subscription.last_result_count is not None
            else "尚未檢查"
        )
        lines.append(
            f"#{subscription.id} {subscription.name}｜{subscription.status.value}｜{last_count}"
        )
    return "\n".join(lines)


def listing_notification(listing: RentalListing) -> str:
    details = [
        f"租金：{listing.price_monthly:,} 元/月",
        f"地點：{listing.location}",
    ]
    if listing.layout:
        details.append(f"格局：{listing.layout}")
    if listing.area_ping is not None:
        details.append(f"坪數：{listing.area_ping:g} 坪")
    if listing.floor:
        details.append(f"樓層：{listing.floor}")
    if listing.published_text:
        details.append(f"刊登：{listing.published_text}")

    return "\n".join(
        [
            f"新房源：{listing.title}",
            *details,
            f"連結：{listing.url}",
        ]
    )


def test_result_message(subscription_id: int, total_count: int, parsed_count: int) -> str:
    return (
        f"測試完成：訂閱 #{subscription_id}\n"
        f"591 顯示約 {total_count} 筆，這次可解析 {parsed_count} 筆。\n"
        "此測試不會改變已通知狀態。"
    )
