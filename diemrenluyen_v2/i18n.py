"""English/Vietnamese user-facing strings.

The English text is the lookup key; ``t(lang, key)`` returns the Vietnamese
translation when ``lang == "vi"`` and the English text otherwise.
"""

from __future__ import annotations

VIETNAMESE: dict[str, str] = {
    # ---- onboarding ----
    "Choose your language:": "Chọn ngôn ngữ của bạn:",
    "Welcome to DiemRenLuyen Bot!": "Chào mừng bạn đến với DiemRenLuyen Bot!",
    "I notify you about school events posted on Facebook, so you never miss events that count toward your training points (điểm rèn luyện).":
        "Mình sẽ thông báo các sự kiện của trường được đăng trên Facebook, để bạn không bỏ lỡ sự kiện tính điểm rèn luyện.",
    "Which school(s) do you want to follow? Tap to select, then press Done.":
        "Bạn muốn theo dõi trường nào? Chạm để chọn, rồi nhấn Xong.",
    "Done": "Xong",
    "No schools are available yet. An admin needs to add schools first — please check back later.":
        "Chưa có trường nào. Quản trị viên cần thêm trường trước — bạn vui lòng quay lại sau nhé.",
    "You're subscribed to:": "Bạn đã đăng ký theo dõi:",
    "You'll receive new event posts from these schools' Facebook pages.":
        "Bạn sẽ nhận bài viết sự kiện mới từ các trang Facebook của các trường này.",
    "You're not subscribed to any school yet. Use /schools to pick your schools.":
        "Bạn chưa đăng ký theo dõi trường nào. Dùng /schools để chọn trường.",
    "Language set to Vietnamese.":
        "Đã đặt ngôn ngữ: Tiếng Việt.",
    "Language set to English.":
        "Đã đặt ngôn ngữ: English.",
    # ---- commands ----
    "Available commands:":
        "Các lệnh khả dụng:",
    "/start - set up your language and school subscriptions":
        "/start - thiết lập ngôn ngữ và trường bạn theo dõi",
    "/schools - change the schools you follow":
        "/schools - thay đổi trường bạn theo dõi",
    "/subscribe <school> - follow a school":
        "/subscribe <tên trường> - theo dõi một trường",
    "/unsubscribe <school> - stop following a school":
        "/unsubscribe <tên trường> - ngừng theo dõi một trường",
    "/mysubscriptions - list the schools you follow":
        "/mysubscriptions - xem các trường bạn đang theo dõi",
    "/addpage - suggest a Facebook page to watch":
        "/addpage - đề xuất một trang Facebook để theo dõi",
    "/mypages - list pages you suggested and their status":
        "/mypages - xem các trang bạn đã đề xuất và trạng thái",
    "/language - change language (EN/VI)":
        "/language - đổi ngôn ngữ (EN/VI)",
    "/help - show this help":
        "/help - xem trợ giúp này",
    "Schools you follow:": "Các trường bạn đang theo dõi:",
    "You don't follow any school yet.": "Bạn chưa theo dõi trường nào.",
    "Subscribed to {name}.": "Đã đăng ký theo dõi {name}.",
    "Unsubscribed from {name}.": "Đã ngừng theo dõi {name}.",
    "You're already subscribed to {name}.": "Bạn đã theo dõi {name} rồi.",
    "You're not subscribed to {name}.": "Bạn chưa theo dõi {name}.",
    "I couldn't find a school matching {query}. Use /schools to browse all schools.":
        "Mình không tìm thấy trường nào khớp với {query}. Dùng /schools để xem tất cả các trường.",
    "Please give a school name or ID, e.g. /subscribe 2":
        "Hãy cho mình tên hoặc mã trường, ví dụ /subscribe 2",
    # ---- add page flow ----
    "Send me the Facebook page link or numeric Page ID you want to suggest.":
        "Hãy gửi mình liên kết trang Facebook hoặc mã số Trang bạn muốn đề xuất.",
    "You can type /cancel anytime to stop.":
        "Bạn có thể gõ /cancel bất cứ lúc nào để dừng.",
    "Cancelled.": "Đã hủy.",
    "I couldn't understand that as a Facebook page. Send a facebook.com link or a numeric Page ID.":
        "Mình không hiểu đây là trang Facebook nào. Hãy gửi liên kết facebook.com hoặc mã số Trang.",
    "Got it. Add a short note about this page (e.g. which school it's for), or /skip.":
        "Đã nhận. Hãy thêm ghi chú ngắn về trang này (ví dụ: của trường nào), hoặc /skip để bỏ qua.",
    "Thanks! Your suggestion is waiting for admin review. I'll notify you when it's approved.":
        "Cảm ơn! Đề xuất của bạn đang chờ quản trị viên duyệt. Mình sẽ báo khi được phê duyệt.",
    "You already suggested this page — it's currently {status}.":
        "Bạn đã đề xuất trang này rồi — trạng thái hiện tại: {status}.",
    "Pages you suggested:": "Các trang bạn đã đề xuất:",
    "You haven't suggested any pages yet.": "Bạn chưa đề xuất trang nào.",
    "pending review": "đang chờ duyệt",
    "approved": "đã duyệt",
    "rejected": "bị từ chối",
    "disabled": "đã tắt",
    # ---- notifications ----
    "New event post": "Bài viết sự kiện mới",
    "(Photo, video, or post without text)": "(Ảnh, video, hoặc bài viết không có nội dung chữ)",
    "Open on Facebook": "Mở trên Facebook",
    # ---- misc user ----
    "I didn't understand that. Try /help.":
        "Mình không hiểu. Hãy thử /help.",
    "This bot only understands commands — try /help.":
        "Bot chỉ hiểu các lệnh — hãy thử /help.",
    # ---- admin ----
    "Admin only.": "Chỉ dành cho quản trị viên.",
    "Pending page suggestions:": "Các đề xuất trang đang chờ duyệt:",
    "No pending suggestions.": "Không có đề xuất nào đang chờ.",
    "Suggested by {user}": "Được đề xuất bởi {user}",
    "Note: {note}": "Ghi chú: {note}",
    "Usage: /approvepage <id>": "Cách dùng: /approvepage <mã>",
    "No pending page with ID {id}.": "Không có đề xuất nào đang chờ với mã {id}.",
    "Now send me the Facebook Page access token for {name}. (Tip: delete your token message afterwards.)":
        "Bây giờ hãy gửi mình mã truy cập Trang Facebook cho {name}. (Mẹo: hãy xóa tin nhắn chứa mã sau khi gửi.)",
    "Meta could not verify this page/token: {error}":
        "Meta không thể xác minh trang/mã này: {error}",
    "Page {name} approved and is now being watched.":
        "Trang {name} đã được duyệt và đang được theo dõi.",
    "Usage: /rejectpage <id>": "Cách dùng: /rejectpage <mã>",
    "Page suggestion {id} rejected.": "Đã từ chối đề xuất trang {id}.",
    "Usage: /addschool <name>": "Cách dùng: /addschool <tên trường>",
    "School {name} added with ID {id}.": "Đã thêm trường {name} với mã {id}.",
    "That school already exists.": "Trường này đã tồn tại.",
    "Usage: /addpageadmin <school_id> <fb_page_id_or_link> <token> [page name]":
        "Cách dùng: /addpageadmin <mã trường> <mã hoặc link trang FB> <mã token> [tên trang]",
    "Usage: /disablepage <id>": "Cách dùng: /disablepage <mã>",
    "Usage: /enablepage <id>": "Cách dùng: /enablepage <mã>",
    "Page {id} disabled — it will no longer be polled.":
        "Đã tắt trang {id} — sẽ không kiểm tra nữa.",
    "Page {id} re-enabled.": "Đã bật lại trang {id}.",
    "No page with ID {id}.": "Không có trang nào với mã {id}.",
    "Broadcast sent to {n} subscriber(s).": "Đã gửi thông báo đến {n} người đăng ký.",
    "Usage: /broadcast <message>": "Cách dùng: /broadcast <nội dung>",
    "Bot stats:": "Thống kê bot:",
    "users: {n}": "người dùng: {n}",
    "active users: {n}": "người dùng đang hoạt động: {n}",
    "schools: {n}": "trường: {n}",
    "pages (approved): {n}": "trang (đã duyệt): {n}",
    "pages (pending): {n}": "trang (chờ duyệt): {n}",
    "subscriptions: {n}": "lượt đăng ký: {n}",
    "Schools:": "Các trường:",
    "Pages:": "Các trang:",
    "No schools yet.": "Chưa có trường nào.",
    "No pages yet.": "Chưa có trang nào.",
}


def t(language: str, text: str, **values: object) -> str:
    """Translate ``text`` to Vietnamese when ``language == "vi"``."""
    translated = VIETNAMESE.get(text, text) if language == "vi" else text
    return translated.format(**values)


def supported_languages() -> tuple[str, str]:
    return ("en", "vi")
