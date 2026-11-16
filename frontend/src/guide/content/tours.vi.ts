import { ADMIN_PERMISSIONS, CURATION_PERMISSIONS } from '@/router/routes'
import type { TourDef } from '../tours'

export const TOURS: TourDef[] = [
  {
    key: 'layout',
    version: 1,
    title: 'Hướng dẫn hệ thống',
    steps: [
      {
        title: 'Chào mừng đến Kho tri thức doanh nghiệp',
        description:
          'Đây là nơi lưu trữ chính sách, quy trình và kinh nghiệm của công ty. Trong một phút tới chúng tôi sẽ giới thiệu các tính năng chính. Bạn có thể đóng hướng dẫn bất cứ lúc nào ở góc trên bên phải, và xem lại sau trong mục «Trợ giúp».',
      },
      {
        target: 'menu-assistant',
        title: 'Chuyên gia hỏi đáp tri thức',
        description:
          'Hỏi bằng ngôn ngữ thường ngày. AI trả lời dựa trên các kho tri thức bạn được phép truy cập và trích dẫn nguồn cho từng câu.',
        placement: 'right',
        permission: 'chat:use',
      },
      {
        target: 'menu-knowledge',
        title: 'Kho tri thức',
        description:
          'Duyệt tài liệu theo kho tri thức và mở chi tiết cùng tệp gốc. Đồng nghiệp có quyền có thể tạo kho tri thức và tải tài liệu lên.',
        placement: 'right',
        permission: 'kb:read',
      },
      {
        target: 'menu-search',
        title: 'Tìm kiếm',
        description:
          'Tìm kiếm lai từ khóa và ngữ nghĩa, lọc theo kho tri thức, loại tài liệu, thẻ và ngày thêm vào.',
        placement: 'right',
        permission: 'search:use',
      },
      {
        target: 'menu-curation',
        title: 'Vận hành tri thức',
        description:
          'Xử lý các khoảng trống tri thức mà AI chưa trả lời được, duy trì mục tri thức và rà soát trước khi xuất bản.',
        placement: 'right',
        permission: CURATION_PERMISSIONS,
      },
      {
        target: 'menu-admin',
        title: 'Quản trị',
        description:
          'Cấu hình hậu trường: phòng ban và người dùng, đồng bộ danh bạ, vai trò và quyền, mô hình, chỉ mục và chiến lược truy xuất.',
        placement: 'right',
        permission: ADMIN_PERMISSIONS,
      },
      {
        target: 'menu-analytics',
        title: 'Phân tích',
        description:
          'Dữ liệu vận hành như lượng câu hỏi, câu hỏi phổ biến, trích dẫn tài liệu và sử dụng mô hình.',
        placement: 'right',
        permission: 'analytics:view',
      },
      {
        target: 'global-search',
        title: 'Tìm kiếm toàn cục',
        description:
          'Gõ từ khóa và nhấn Enter ở bất kỳ trang nào để tìm. Nhấn Ctrl + K để nhảy thẳng vào ô tìm.',
        placement: 'bottom',
        permission: 'search:use',
      },
      {
        target: 'notifications',
        title: 'Thông báo',
        description:
          'Cập nhật về yêu cầu tri thức, nhiệm vụ duyệt và nhắc hết hạn tài liệu hiển thị tại đây.',
        placement: 'bottom',
      },
      {
        target: 'theme',
        title: 'Giao diện',
        description: 'Chuyển giữa sáng, tối và theo cài đặt hệ thống.',
        placement: 'bottom',
      },
      {
        target: 'help',
        title: 'Trợ giúp',
        description:
          'Mở «Hướng dẫn sử dụng» để xem hướng dẫn từng bước cho mọi tính năng, hoặc phát lại hướng dẫn của trang hiện tại.',
        placement: 'bottom-start',
      },
    ],
  },
  {
    key: 'assistant',
    version: 1,
    title: 'Hướng dẫn Chuyên gia hỏi đáp tri thức',
    routeName: 'assistant',
    permission: 'chat:use',
    steps: [
      {
        target: 'assistant-composer',
        title: 'Nhập câu hỏi',
        description:
          'Mô tả câu hỏi như khi hỏi đồng nghiệp. Nhấn Enter để gửi và Shift + Enter để xuống dòng. Câu hỏi càng cụ thể thì câu trả lời càng chính xác.',
        placement: 'top',
      },
      {
        target: 'assistant-scope',
        title: 'Giới hạn kho tri thức (tùy chọn)',
        description:
          'Mặc định trợ lý tìm trong mọi kho tri thức bạn truy cập được. Chọn các kho cụ thể tại đây để chỉ tìm trong những kho đó.',
        placement: 'top',
      },
      {
        title: 'Trích dẫn và tài liệu nguồn',
        description:
          'Số màu xanh trong câu trả lời là trích dẫn. Di chuột để xem trước đoạn nguồn, hoặc nhấn «Xem nguồn» hoặc thẻ nguồn dưới câu trả lời để mở toàn bộ tài liệu.',
      },
      {
        title: 'Phản hồi và yêu cầu tri thức',
        description:
          'Nhấn «Hữu ích / Không hữu ích» dưới câu trả lời để đánh giá. Nếu kho tri thức chưa có câu trả lời, nhấn «Yêu cầu tri thức» — đội vận hành sẽ bổ sung nội dung và thông báo cho bạn.',
      },
      {
        target: 'assistant-new',
        title: 'Cuộc trò chuyện mới',
        description:
          'Bắt đầu cuộc trò chuyện mới khi đổi chủ đề, tránh trộn ngữ cảnh trước đó.',
        placement: 'right',
      },
      {
        target: 'assistant-history',
        title: 'Lịch sử trò chuyện',
        description:
          'Các cuộc trò chuyện trước được lưu theo ngày tại đây. Bạn có thể tìm, đổi tên hoặc xóa.',
        placement: 'right',
      },
    ],
  },
  {
    key: 'knowledge',
    version: 1,
    title: 'Hướng dẫn Kho tri thức',
    routeName: 'knowledge',
    permission: 'kb:read',
    steps: [
      {
        target: 'kb-search',
        title: 'Tìm kho tri thức',
        description: 'Lọc các kho tri thức bạn truy cập được theo tên hoặc mô tả.',
        placement: 'bottom',
      },
      {
        target: 'kb-create',
        title: 'Kho tri thức mới',
        description:
          'Thiết lập kho riêng cho phòng ban hoặc dự án, chọn phạm vi hiển thị và quyền thành viên.',
        placement: 'bottom',
        permission: 'kb:create',
      },
      {
        target: 'kb-table',
        title: 'Mở kho tri thức',
        description:
          'Nhấp một dòng để mở kho tri thức: xem tài liệu, tải lên mới hoặc điều chỉnh quyền.',
        placement: 'top',
      },
    ],
  },
  {
    key: 'kb-detail',
    version: 1,
    title: 'Hướng dẫn chi tiết kho tri thức',
    routeName: 'knowledge-base',
    permission: 'kb:read',
    steps: [
      {
        target: 'kb-upload',
        title: 'Tải tài liệu lên',
        description:
          'Hỗ trợ PDF, Word, Excel, PowerPoint, Markdown và nhiều định dạng khác. Tệp được phân tích, chia khối và lập chỉ mục tự động, sau đó có thể tìm thấy trong tìm kiếm và được Chuyên gia hỏi đáp trích dẫn.',
        placement: 'bottom',
      },
      {
        target: 'kb-acl',
        title: 'Quyền truy cập',
        description:
          'Cấp quyền cho phòng ban, nhóm người dùng hoặc vai trò để quyết định ai xem hoặc chỉnh sửa kho tri thức này.',
        placement: 'bottom',
      },
      {
        target: 'kb-docs',
        title: 'Danh sách tài liệu',
        description:
          'Cột «Trạng thái» hiển thị tiến độ xử lý. Tài liệu đang xử lý chưa tìm được; nếu thất bại, xem lý do và tải lại. Nhấp tiêu đề để xem chi tiết và phiên bản.',
        placement: 'top',
      },
    ],
  },
  {
    key: 'search',
    version: 1,
    title: 'Hướng dẫn Tìm kiếm',
    routeName: 'search',
    permission: 'search:use',
    steps: [
      {
        target: 'search-input',
        title: 'Nhập từ khóa hoặc câu hỏi',
        description:
          'Gõ từ khóa hoặc số tài liệu, hoặc đặt câu hỏi trực tiếp. Tìm kiếm khớp cả từ khóa lẫn ngữ nghĩa.',
        placement: 'bottom',
      },
      {
        target: 'search-filters',
        title: 'Lọc kết quả',
        description:
          'Thu hẹp theo kho tri thức, loại tài liệu, thẻ hoặc ngày thêm. Tìm kiếm tự chạy lại khi đổi bộ lọc.',
        placement: 'bottom',
      },
      {
        target: 'search-syntax',
        title: 'Cú pháp nâng cao',
        description:
          'Có thể gõ bộ lọc trực tiếp trong ô tìm, ví dụ kb:HR-Policies type:pdf. Văn bản trong dấu ngoặc kép khớp cụm chính xác.',
        placement: 'bottom',
      },
    ],
  },
]