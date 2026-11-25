import { ADMIN_AGENT_PERMISSIONS, ADMIN_PERMISSIONS, CURATION_PERMISSIONS } from '@/router/routes'
import type { ManualFaq, ManualSection } from '../manual'

/** Menu kỹ thuật nền tảng (nhóm con trong Quản trị). */
const PLATFORM_PERMISSIONS = [
  'admin:index',
  'admin:model',
  'admin:retrieval',
  'admin:openapi',
] as const

export const MANUAL_SECTIONS: ManualSection[] = [
  {
    id: 'start',
    title: 'Bắt đầu nhanh',
    icon: 'Promotion',
    summary: 'Đăng nhập, làm quen giao diện và tìm đúng tính năng cho vai trò của bạn.',
    tourKey: 'layout',
    topics: [
      {
        title: 'Lần đầu truy cập',
        steps: [
          {
            title: 'Đăng nhập',
            detail:
              'Mở URL trang và dùng tài khoản công ty cùng mật khẩu, hoặc chọn WeCom / DingTalk và quét mã QR. Nếu thấy “forbidden”, tài khoản của bạn chưa có vai trò, hãy liên hệ quản trị viên.',
          },
          {
            title: 'Làm quen bố cục',
            detail:
              'Thanh bên trái liệt kê các tính năng bạn được phép sử dụng. Phần đầu trang có tìm kiếm toàn cục (Ctrl/Cmd+K), trạng thái sẵn sàng, Trợ giúp, giao diện, ngôn ngữ, thông báo và menu tài khoản. Ở giữa là vùng làm việc; các tab phía trên dùng để chuyển giữa các trang đang mở.',
          },
          {
            title: 'Trợ giúp và hướng dẫn',
            detail:
              'Trợ giúp → Hướng dẫn sử dụng sẽ mở sổ tay này (các mục được lọc theo quyền của bạn). “Phát lại hướng dẫn cho trang này” sẽ khởi động lại hướng dẫn của trang hiện tại; “Khởi động lại tất cả hướng dẫn” sẽ bắt đầu lại từ hướng dẫn bố cục. Nên xem hướng dẫn trước, rồi đọc chương tương ứng tại đây.',
          },
        ],
      },
      {
        title: 'Theo vai trò',
        steps: [
          {
            title: 'Nhân viên (tìm câu trả lời)',
            detail:
              'Lộ trình thường gặp: ① vào “Chuyên gia hỏi đáp tri thức” để đặt câu hỏi và kiểm tra trích dẫn; ② dùng Tìm kiếm hoặc tìm kiếm đầu trang để xem văn bản gốc; ③ vào “Kho tri thức” để duyệt tài liệu bạn được phép truy cập; ④ dùng “Yêu thích của tôi” để mở nhanh tài liệu thường dùng. Các menu tải lên, ACL và vận hành thường sẽ bị ẩn.',
          },
          {
            title: 'Vận hành tri thức (lấp khoảng trống, duyệt)',
            detail:
              'Lộ trình thường gặp: ① vào “Khoảng trống tri thức” để xử lý các nhu cầu chưa được trả lời; ② vào “Mục tri thức” để biên soạn hỏi đáp chuẩn, câu hỏi tương tự và quan hệ liên kết rồi gửi duyệt; ③ dùng “Duyệt xuất bản” để đưa nội dung vào chỉ mục. Hãy đọc trước chương “Lớp khái niệm” để nắm rõ thuật ngữ và đồ thị. Bạn cũng có thể tải lên hoặc chỉnh sửa tài liệu.',
            permission: CURATION_PERMISSIONS,
          },
          {
            title: 'Quản trị / nền tảng',
            detail:
              'Phần tổ chức gồm: phòng ban, người dùng, đồng bộ danh bạ, nhóm, vai trò, kiểm toán. Phần khái niệm gồm: “Thuật ngữ” và “Dữ liệu có cấu trúc” (xem thêm ở chương “Lớp khái niệm” và “Quản trị”). Phần nền tảng (Quản trị → Kỹ thuật nền tảng) gồm: chỉ mục, mô hình, truy xuất, đánh giá, Open API. Ngoài ra còn có “Trợ lý quản trị AI”. Các nội dung sao lưu/cảnh báo/quét virus nằm trong tài liệu vận hành.',
            permission: ADMIN_PERMISSIONS,
          },
        ],
      },
      {
        title: 'Hỏi trong ba bước',
        permission: 'chat:use',
        steps: [
          {
            title: 'Mở hỏi đáp',
            detail: 'Nhấp “Chuyên gia hỏi đáp tri thức” trên thanh bên.',
          },
          {
            title: 'Gõ câu hỏi',
            detail:
              'Trong ô phía dưới, nêu rõ đối tượng, bối cảnh và thời gian (ví dụ: “quy trình đánh giá thử việc nhân viên mới năm 2026”), rồi nhấn Enter để gửi (Shift+Enter để xuống dòng).',
          },
          {
            title: 'Kiểm tra nguồn',
            detail:
              'Các số màu xanh trong câu trả lời là trích dẫn. Di chuột để xem trước; mở “Xem nguồn” để vào tài liệu. Với chính sách, tiền hoặc ngày tháng, hãy lấy văn bản gốc làm chuẩn.',
          },
        ],
      },
    ],
  },
  {
    id: 'assistant',
    title: 'Chuyên gia hỏi đáp tri thức',
    icon: 'ChatDotRound',
    summary: 'Hỏi bằng ngôn ngữ tự nhiên; câu trả lời chỉ dựa trên nội dung bạn được phép truy cập và luôn kèm trích dẫn.',
    permission: 'chat:use',
    route: '/assistant',
    tourKey: 'assistant',
    topics: [
      {
        title: 'Đặt câu hỏi và hỏi tiếp',
        steps: [
          {
            title: 'Gửi câu hỏi',
            detail:
              'Nhập nội dung vào ô phía dưới rồi nhấn Enter. Bạn có thể dùng nút dừng hình vuông để hủy; dùng “Tạo lại” nếu chưa hài lòng với câu trả lời gần nhất.',
          },
          {
            title: 'Hỏi tiếp',
            detail:
              'Hãy hỏi tiếp trong cùng một cuộc trò chuyện (ví dụ: “Còn nhân sự nhà thầu thì sao?”). Khi đổi chủ đề, hãy bắt đầu “Cuộc trò chuyện mới” để tránh trộn lẫn ngữ cảnh.',
          },
          {
            title: 'Bảng biểu và hình ảnh',
            detail:
              'Câu trả lời có thể bao gồm bảng (có thể chuyển sang biểu đồ), sơ đồ, mã được tô sáng hoặc hình ảnh tài liệu. Với tài liệu được kiểm soát, tính năng sao chép có thể bị tắt, vì vậy chỉ nên đọc trực tiếp trên màn hình.',
          },
        ],
      },
      {
        title: 'Giới hạn kho tri thức',
        steps: [
          {
            title: 'Chọn phạm vi',
            detail:
              'Mặc định hệ thống sẽ tìm trong tất cả các kho bạn được phép truy cập. Nhấp vào “Tất cả kho tri thức có thể truy cập” bên dưới ô nhập rồi chọn một hoặc nhiều kho.',
          },
          {
            title: 'Xóa phạm vi',
            detail: 'Dùng biểu tượng xóa trên bộ chọn để khôi phục về toàn bộ các kho tri thức có thể truy cập.',
          },
        ],
      },
      {
        title: 'Trích dẫn và nguồn',
        steps: [
          {
            title: 'Xem trước một đoạn',
            detail: 'Di chuột lên số trích dẫn màu xanh để xem đoạn văn được trích dẫn.',
          },
          {
            title: 'Mở tài liệu',
            detail:
              'Chọn “Xem nguồn” trong cửa sổ nổi hoặc một thẻ trong mục “Nguồn”. Ngăn kéo sẽ mở tài liệu gần vị trí được trích; hình ảnh trang sẽ được tải khi cần.',
          },
          {
            title: 'Khi bằng chứng yếu',
            detail:
              'Nếu hệ thống cho biết không tìm thấy cơ sở đáng tin cậy, đừng xem câu trả lời đó là chính sách chính thức. Hãy dùng “Gửi yêu cầu tri thức” để đội vận hành bổ sung nội dung.',
          },
        ],
      },
      {
        title: 'Khái niệm liên quan',
        steps: [
          {
            title: 'Bạn sẽ thấy gì',
            detail:
              'Sau khi có câu trả lời, một khối có thể thu gọn mang tên “Khái niệm liên quan” có thể xuất hiện khi hệ thống khớp được thuật ngữ hoặc tri thức liên kết. Mỗi mục có thể hiển thị tên chuẩn, loại, bí danh, mã thiết bị/mã bên ngoài và tiêu đề của các mục tri thức liên quan, giúp bạn đối chiếu cách gọi nội bộ với tên chuẩn trong hệ thống.',
          },
          {
            title: 'Cách sử dụng',
            detail:
              'Hãy mở rộng khối này và kiểm tra xem bí danh cùng mã định danh có đúng với điều bạn muốn hỏi hay không. Phần tri thức liên quan cũng có thể gợi ý thêm các hỏi đáp chuẩn khác. Khối này chỉ để đọc đối với nhân viên. Nếu khái niệm sai hoặc còn thiếu, hãy gửi yêu cầu tri thức hoặc chọn “Không hữu ích” để đội vận hành chỉnh sửa trong Thuật ngữ, Dữ liệu có cấu trúc hoặc Mục tri thức.',
          },
        ],
      },
      {
        title: 'Phản hồi và yêu cầu tri thức',
        steps: [
          {
            title: 'Đánh giá câu trả lời',
            detail: 'Nhấp “Hữu ích” để ghi nhận; chọn “Không hữu ích” để nêu lý do và bổ sung ghi chú.',
          },
          {
            title: 'Gửi yêu cầu tri thức',
            detail:
              'Khi không có nội dung nào trả lời đúng nhu cầu của bạn, hãy gửi một yêu cầu. Sau khi đội vận hành xử lý xong, bạn sẽ nhận được thông báo ở biểu tượng chuông trên đầu trang.',
          },
        ],
      },
      {
        title: 'Quản lý cuộc trò chuyện',
        steps: [
          {
            title: 'Cuộc trò chuyện mới',
            detail: 'Dùng “Cuộc trò chuyện mới” ở góc trên bên trái để bắt đầu một phiên trống.',
          },
          {
            title: 'Tìm, đổi tên, xóa',
            detail:
              'Danh sách bên trái được nhóm theo thời gian và có thể tìm kiếm. Dùng nút “…” trên một cuộc trò chuyện để đổi tên hoặc xóa. Chỉ bạn mới nhìn thấy danh sách trò chuyện của mình.',
          },
        ],
      },
    ],
  },
  {
    id: 'knowledge',
    title: 'Kho tri thức',
    icon: 'Collection',
    summary: 'Tổ chức tài liệu: tải lên, chỉnh sửa trực tuyến, ACL, phiên bản và tác vụ hàng loạt.',
    permission: 'kb:read',
    route: '/knowledge',
    tourKey: 'knowledge',
    topics: [
      {
        title: 'Duyệt tài liệu',
        steps: [
          {
            title: 'Tìm một kho',
            detail:
              'Mở “Kho tri thức” và lọc theo tên hoặc mô tả. Bạn chỉ nhìn thấy những kho mà mình được phép truy cập; nhấp vào tên kho để mở.',
          },
          {
            title: 'Mở tài liệu',
            detail:
              'Trên trang chi tiết, hãy lọc theo tiêu đề, trạng thái hoặc thẻ; mở một tài liệu để xem nội dung, các đoạn chunk, lịch sử phiên bản và bình luận.',
          },
        ],
      },
      {
        title: 'Tạo kho tri thức',
        permission: 'kb:create',
        steps: [
          {
            title: 'Tạo mới',
            detail:
              'Nhấp “Kho tri thức mới”, nhập tên và mô tả, rồi chọn mức hiển thị: đọc được trong toàn tổ chức hoặc chỉ dành cho thành viên được cấp quyền.',
          },
          {
            title: 'Mẫu kiểm soát (tùy chọn)',
            detail:
              'Nếu có mẫu “Controlled”, hệ thống sẽ bật sẵn watermark, chống sao chép, yêu cầu quyền chỉnh sửa để tải xuống và giới hạn hiển thị cho thành viên được cấp quyền. Phù hợp với tài liệu chính sách và tài liệu nhạy cảm.',
          },
          {
            title: 'Cấp quyền truy cập',
            detail:
              'Mở “Permissions” và cấp quyền xem / chỉnh sửa / quản lý cho phòng ban (bao gồm cấp con), nhóm, vai trò hoặc người dùng. Thay đổi có hiệu lực ngay.',
          },
        ],
      },
      {
        title: 'ACL cho phép và từ chối',
        permission: 'kb:create',
        steps: [
          {
            title: 'Cấp phép cho phép',
            detail:
              'Thêm các principal và mức quyền trong Permissions. Những kho hiển thị cho toàn tổ chức vẫn có thể dùng ACL tài liệu chi tiết hơn.',
          },
          {
            title: 'Danh sách từ chối',
            detail:
              'Khi dùng hiệu lực deny, người dùng hoặc phòng ban bị từ chối sẽ không thể thấy tài nguyên dù vẫn tồn tại các quyền cho phép khác (deny-wins). Quản lý KB vẫn có thể vào để sửa ACL. Bộ nhớ đệm sẽ bị vô hiệu sau khi thay đổi; hỏi đáp cũng sẽ kiểm tra lại quyền.',
          },
        ],
      },
      {
        title: 'Tải lên và duy trì tài liệu',
        permission: 'doc:upload',
        steps: [
          {
            title: 'Tải lên',
            detail:
              'Trên trang chi tiết kho, nhấp “Upload”, kéo thả hoặc chọn tệp (có thể chọn nhiều). Hỗ trợ PDF, Word (.docx/.doc), Excel, PPT (.pptx), TXT, Markdown, HTML và nhiều định dạng khác; nội dung trùng lặp sẽ được loại trừ.',
          },
          {
            title: 'Chờ xử lý',
            detail:
              'Tệp sẽ được phân tích, chia đoạn và lập chỉ mục. Hãy theo dõi cột Status (parsing / indexing / ready / failed). Khi ở trạng thái ready, tài liệu có thể được tìm thấy và trích dẫn, thường mất từ vài giây đến vài phút.',
          },
          {
            title: 'Lỗi xử lý',
            detail:
              'Di chuột lên trạng thái failed để xem nguyên nhân (mã hóa, bản quét trống, loại tệp không hỗ trợ). Khắc phục rồi tải lại, hoặc dùng “Reprocess” trên tài liệu.',
          },
          {
            title: 'Phiên bản mới',
            detail:
              'Tải lại tệp cùng tên sẽ tạo một phiên bản mới; các phiên bản cũ vẫn nằm trong lịch sử phiên bản ở trang tài liệu.',
          },
        ],
      },
      {
        title: 'Chỉnh sửa trực tuyến và cộng tác',
        permission: 'doc:upload',
        steps: [
          {
            title: 'Tài liệu trực tuyến mới',
            detail:
              'Chọn “New document” (hoặc mục tương đương), soạn thảo trong trình chỉnh sửa Markdown rồi lưu. Việc lưu sẽ kích hoạt cùng một quy trình phân tích và lập chỉ mục.',
          },
          {
            title: 'Chỉnh sửa tài liệu hiện có',
            detail: 'Khi có quyền chỉnh sửa, hãy mở “Edit” trên trang tài liệu và lưu thành một phiên bản mới.',
          },
          {
            title: 'Người phụ trách, rà soát, bình luận',
            detail:
              'Chỉ định người phụ trách và chu kỳ rà soát; để lại bình luận trên trang chi tiết. Khi đến hạn rà soát, hệ thống sẽ thông báo cho đúng người theo cấu hình.',
          },
          {
            title: 'Yêu thích',
            detail: 'Gắn sao cho một tài liệu trên trang chi tiết rồi mở lại sau từ “Yêu thích của tôi”.',
          },
        ],
      },
      {
        title: 'Xử lý lại hàng loạt và thiếu ảnh trang',
        permission: 'doc:upload',
        steps: [
          {
            title: 'Xử lý lại hàng loạt',
            detail:
              'Chọn nhiều tài liệu và chạy “Reprocess” (hoặc thao tác hàng loạt) sau khi có lỗi hoặc thay đổi quy tắc. Tránh gửi dồn dập những mục vẫn đang ở trạng thái parsing.',
          },
          {
            title: 'Bộ lọc thiếu ảnh trang',
            detail:
              'Nếu danh sách có bộ lọc “missing page images”, hãy dùng nó để tìm các tài liệu đáng ra phải có ảnh raster của trang/slide nhưng đã thất bại, rồi chạy lại xử lý.',
          },
        ],
      },
    ],
  },
  {
    id: 'search',
    title: 'Tìm kiếm',
    icon: 'Search',
    summary: 'Tìm kiếm lai giữa từ khóa và ngữ nghĩa để mở đúng tài liệu nguồn.',
    permission: 'search:use',
    route: '/search',
    tourKey: 'search',
    topics: [
      {
        title: 'Tìm kiếm cơ bản',
        steps: [
          {
            title: 'Nhập truy vấn',
            detail:
              'Dùng ô tìm kiếm ở đầu trang (Ctrl/Cmd+K) hoặc trang Tìm kiếm. Nhập từ khóa, mã tài liệu hoặc một câu hỏi đầy đủ rồi nhấn Enter. Hệ thống chỉ trả về nội dung bạn được phép xem.',
          },
          {
            title: 'Đọc kết quả',
            detail:
              'Kết quả được xếp hạng kèm phần tô sáng; nhấp vào tiêu đề để mở tài liệu. Nếu không có kết quả, hãy đổi từ khóa, xóa bộ lọc hoặc kiểm tra quyền truy cập.',
          },
        ],
      },
      {
        title: 'Bộ lọc và cú pháp nội dòng',
        steps: [
          {
            title: 'Bộ lọc',
            detail:
              'Lọc theo kho tri thức, loại, thẻ và thời gian nhập kho; tìm kiếm sẽ tự làm mới. “Xóa bộ lọc” sẽ đưa mọi thứ về mặc định.',
          },
          {
            title: 'Cú pháp nội dòng',
            detail:
              'Trong ô tìm kiếm, bạn có thể dùng: kb:name, tag:label, type:pdf, date:2026-03, after:2026-01-01; văn bản đặt trong dấu ngoặc kép sẽ khớp chính xác cụm từ.',
          },
        ],
      },
    ],
  },
  {
    id: 'favorites',
    title: 'Yêu thích của tôi',
    icon: 'Star',
    summary: 'Gắn sao cho tài liệu và mục tri thức; đồng thời duyệt các mục đã xem gần đây.',
    permission: 'kb:read',
    route: '/favorites',
    topics: [
      {
        title: 'Yêu thích và gần đây',
        steps: [
          {
            title: 'Mở trang',
            detail: 'Nhấp “Yêu thích của tôi”. Dùng các tab Yêu thích và Đã xem gần đây.',
          },
          {
            title: 'Mở một mục',
            detail: 'Nhấp vào tiêu đề để mở tài liệu hoặc mục tri thức.',
          },
          {
            title: 'Bỏ yêu thích',
            detail: 'Nhấp lại biểu tượng ngôi sao trong danh sách hoặc trên trang chi tiết để bỏ đánh dấu. Các mục gần đây được ghi nhận tự động.',
          },
        ],
      },
    ],
  },
  {
    id: 'notifications',
    title: 'Thông báo',
    icon: 'Bell',
    summary: 'Các cảnh báo trong ứng dụng như kết quả xử lý yêu cầu tri thức.',
    route: '/notifications',
    topics: [
      {
        title: 'Đọc thông báo',
        steps: [
          {
            title: 'Điểm vào',
            detail: 'Nhấp vào biểu tượng chuông ở đầu trang hoặc “Thông báo” trong menu tài khoản. Huy hiệu hiển thị số lượng chưa đọc.',
          },
          {
            title: 'Mở và đánh dấu đã đọc',
            detail: 'Mở một mục để xem chi tiết; mục đó sẽ được đánh dấu là đã đọc. Các loại phổ biến gồm: yêu cầu tri thức đã hoàn thành, nhắc rà soát.',
          },
          {
            title: 'Danh sách trống',
            detail: 'Không có dòng nào nghĩa là hiện chưa có gì chờ xử lý. Sau khi bạn gửi yêu cầu tri thức, hãy chờ đội vận hành hoàn tất trước khi có thông báo đẩy.',
          },
        ],
      },
    ],
  },
  {
    id: 'concepts',
    title: 'Lớp khái niệm (thuật ngữ · thực thể · đồ thị · bản thể học)',
    icon: 'Connection',
    summary:
      'Căn chỉnh tên chuẩn, quan hệ và mã thiết bị để tìm kiếm và hỏi đáp khớp tốt hơn, không dùng SPARQL hay graph DB.',
    permission: [
      'chat:use',
      'gap:review',
      'ko:edit',
      'review:approve',
      'admin:retrieval',
    ],
    topics: [
      {
        title: 'Vì sao nó tồn tại',
        steps: [
          {
            title: 'Vấn đề mà nó giải quyết',
            detail:
              'Cùng một sự vật có thể có tiếng lóng, mã hiệu và cách gọi miệng; tài liệu cũng thường nhắc đến mã thiết bị và mã lệnh công việc. Lớp khái niệm duy trì tên chuẩn + bí danh + loại, quan hệ giữa các mục tri thức và ánh xạ mã bên ngoài để truy xuất có thể mở rộng thuật ngữ, hỏi đáp có thể gắn thêm khái niệm liên quan, và kết quả trúng mục tri thức có thể đi nhiều bước theo quan hệ.',
          },
          {
            title: 'Ba khối cấu thành',
            detail:
              '① Thuật ngữ = từ điển thực thể (tên chuẩn, loại, bí danh); ② Mục tri thức (KO) và quan hệ KO = tri thức chuẩn đã được rà soát cùng các cạnh “đồ thị”; ③ Dữ liệu có cấu trúc = các bản sao mã ERP/MES được ánh xạ tới thuật ngữ hoặc KO. Tài liệu vẫn là nguồn văn bản gốc; lớp khái niệm dùng để căn chỉnh cách gọi và liên kết, không thay thế việc tải tài liệu lên.',
          },
          {
            title: 'Nhân viên sẽ thấy gì',
            detail:
              'Khối “Khái niệm liên quan” có thể thu gọn sau phần hỏi đáp (tên chuẩn, bí danh, thiết bị/mã định danh, KO liên quan). Tìm kiếm trên trang không hiển thị thẻ khái niệm riêng nhưng vẫn hưởng lợi từ việc mở rộng bí danh; các kết quả KO sẽ có huy hiệu Mục tri thức. Việc bảo trì nằm trong Quản trị và Vận hành tri thức, không nằm trong menu nhân viên.',
            permission: 'chat:use',
          },
        ],
      },
      {
        title: 'Bảng thuật ngữ',
        steps: [
          {
            title: 'Thực thể / thuật ngữ',
            detail:
              'Một “thực thể” ở đây chủ yếu là một dòng trong Thuật ngữ: tên chuẩn, loại nghiệp vụ (thiết bị, quy trình, lỗi, chính sách, thuật ngữ IT, ...), bí danh và trạng thái bật/tắt. Trong quá trình nhập kho, các đoạn chunk có thể được gắn entity_ids để hỏi đáp mở rộng các đoạn liên quan trong cùng tài liệu.',
          },
          {
            title: 'Đồ thị (quan hệ KO)',
            detail:
              'Đây không phải Neo4j mà là các cạnh giữa các mục tri thức (relatedTo, partOf, dependsOn, causes, mitigates, appliesTo, ...). Khi bật graph recall, một KO được khớp sẽ kéo thêm các mục lân cận để hợp nhất. Đội vận hành chỉnh sửa quan hệ trong trình biên tập KO; “Xem trước quan hệ” của Thuật ngữ hiển thị các thuật ngữ / dữ liệu có cấu trúc / KO xung quanh một thuật ngữ trong phạm vi khoảng 1 bước.',
          },
          {
            title: 'Bản thể học (OWL)',
            detail:
              'Bản thể học là hợp đồng về các lớp và quan hệ được phép (TBox), nằm trong `ontology/enterprise.ttl` (có thể mở bằng Protégé). Các thực thể thời gian chạy (ABox) vẫn được lưu trong PostgreSQL thông qua các trang Thuật ngữ, KO và Dữ liệu có cấu trúc. Hộp thoại Bản thể học trong ứng dụng chỉ để đọc, không có trình chỉnh sửa OWL trên web và cũng không có SPARQL. Mọi thay đổi enum cần phía kỹ thuật đồng bộ cả mã nguồn và TTL.',
            permission: 'admin:retrieval',
          },
        ],
      },
      {
        title: 'Thứ tự bảo trì được khuyến nghị',
        permission: ['admin:retrieval', 'ko:edit', 'gap:review'],
        steps: [
          {
            title: 'Từ điển → tri thức → liên kết',
            detail:
              '① Tạo thuật ngữ và bí danh, sau đó Đồng bộ từ đồng nghĩa; ② Ghi nhận hỏi đáp chuẩn thành các mục tri thức kèm quan hệ; ③ Ánh xạ mã bên ngoài trong Dữ liệu có cấu trúc vào thuật ngữ/KO. Cuối cùng hãy đặt các câu hỏi thực tế và kiểm tra phần Khái niệm liên quan.',
          },
        ],
      },
    ],
  },
  {
    id: 'curation',
    title: 'Vận hành tri thức',
    icon: 'Opportunity',
    summary: 'Khoảng trống tri thức → mục tri thức → duyệt xuất bản; biến những trường hợp chưa trả lời được thành tri thức có thể tìm kiếm.',
    permission: CURATION_PERMISSIONS,
    route: '/curation/gaps',
    topics: [
      {
        title: 'Khoảng trống tri thức là gì',
        permission: 'gap:review',
        steps: [
          {
            title: 'Mục đích',
            detail:
              'Thu thập các trường hợp “không có bằng chứng / bằng chứng yếu / Không hữu ích / yêu cầu tri thức”, gom cụm chúng lại rồi để đội vận hành bổ sung tài liệu hoặc mục tri thức, nhờ đó cùng một thiếu hụt sẽ không lặp lại.',
          },
          {
            title: 'Nhân viên tạo ra khoảng trống như thế nào',
            detail:
              'Trong Chuyên gia hỏi đáp tri thức: nhấp “Không hữu ích” và chọn lý do, hoặc “Gửi yêu cầu tri thức” khi thiếu bằng chứng. Nhân viên không nhìn thấy bảng vận hành; họ sẽ nhận được thông báo khi vấn đề được xử lý.',
          },
        ],
      },
      {
        title: 'Bảng khoảng trống',
        permission: 'gap:review',
        steps: [
          {
            title: 'Mở và đọc thống kê',
            detail:
              'Vận hành tri thức → Khoảng trống tri thức. Các thẻ phía trên hiển thị số cụm đang mở, đang xử lý và chưa giải quyết; nhấp vào các thẻ loại nguồn để lọc (không có bằng chứng, bằng chứng yếu, phản hồi tiêu cực, yêu cầu người dùng).',
          },
          {
            title: 'Lọc danh sách',
            detail:
              'Trong tab Khoảng trống, hãy lọc theo trạng thái, nguồn, kho tri thức và từ khóa; sắp xếp theo tần suất hoặc độ mới; nếu cần có thể dùng “Được giao cho tôi” → Tìm kiếm.',
          },
          {
            title: 'Gom cụm',
            detail:
              'Nhấp Gom cụm ngay để hợp nhất các câu hỏi tương tự. Tab Cụm hiển thị câu hỏi đại diện, số lượng và cơ cấu nguồn; mở một dòng để quay lại danh sách với bộ lọc của cụm đó.',
          },
          {
            title: 'Mở bàn làm việc',
            detail: 'Nhấp vào một dòng để phân công và xử lý khoảng trống.',
          },
        ],
      },
      {
        title: 'Bàn làm việc khoảng trống',
        permission: 'gap:review',
        steps: [
          {
            title: 'Đọc ngữ cảnh',
            detail:
              'Xem lại câu hỏi đã được viết lại và câu hỏi gốc, số lần xuất hiện, điểm truy hồi và các đoạn trích cuộc trò chuyện; hãy mở rộng QA Trace (các bước JSON) khi cần gỡ lỗi.',
          },
          {
            title: 'Phân công',
            detail:
              'Thiết lập người phụ trách, kho tri thức, mức ưu tiên và ngày đến hạn → Lưu, hoặc chọn Giao cho tôi để cả nhóm có thể nhận xử lý các khoảng trống nóng.',
          },
          {
            title: 'Soạn mục tri thức',
            detail:
              'Với quyền `ko:edit`: chọn KB, loại KO, tài liệu tham chiếu tùy chọn và ghi chú → Tạo bản nháp KO. Bạn sẽ được đưa tới trình biên tập KO (AI có thể rơi về bản nháp trống).',
            permission: 'ko:edit',
          },
          {
            title: 'Các cách xử lý khác',
            detail:
              'Liên kết tới tài liệu hiện có: tài liệu đã bao phủ vấn đề đó. Đánh dấu trùng lặp: chọn một khoảng trống cùng loại. Từ chối: bác bỏ yêu cầu. Mở lại nếu cần. Người hỏi sẽ được thông báo khi phù hợp.',
          },
        ],
      },
      {
        title: 'Mục tri thức (KO) là gì',
        permission: ['ko:edit', 'gap:review', 'review:approve'],
        steps: [
          {
            title: 'Mục đích',
            detail:
              'Biến “câu hỏi chuẩn + các cách diễn đạt tương tự + câu trả lời có cấu trúc + tài liệu nguồn” thành một mục có thể được rà soát và lập chỉ mục. Các KO đã xuất bản là kết quả tìm kiếm hạng nhất (thường được tăng điểm) và là nút cho graph recall, phù hợp làm câu trả lời chuẩn hơn là chôn trong văn xuôi dài.',
          },
          {
            title: 'Chọn loại',
            detail:
              'Các loại phổ biến: FAQ, Hỏi đáp, thẻ kiến thức, tóm tắt chính sách, thiết bị, quy trình, lỗi, chính sách, thuật ngữ IT, ... Hãy chọn theo ý nghĩa nghiệp vụ; các kiểm tra mềm của bản thể học có thể cảnh báo khi cặp quan hệ bất thường nhưng sẽ không chặn cứng.',
          },
        ],
      },
      {
        title: 'Viết mục tri thức',
        permission: 'ko:edit',
        steps: [
          {
            title: 'Tạo mới',
            detail:
              'Vận hành tri thức → Mục tri thức → Mới (KB, loại, câu hỏi chuẩn), hoặc Tạo FAQ từ một tài liệu, hoặc tạo bản nháp từ bàn làm việc khoảng trống.',
          },
          {
            title: 'Điền nội dung',
            detail:
              'Chỉnh sửa tiêu đề, loại, câu hỏi chuẩn, các câu hỏi tương tự (mỗi dòng một câu) và câu trả lời (xem trước Markdown). Hãy bao quát các biến thể cách nói trong phần câu hỏi tương tự để khâu viết lại có thể khớp.',
          },
          {
            title: 'Nguồn',
            detail:
              'Đính kèm tài liệu nguồn bằng bộ chọn và nhảy tới vị trí xác minh. Các nhận định quan trọng trong câu trả lời cần phải có cơ sở trước khi xuất bản.',
          },
          {
            title: 'Quan hệ (cạnh đồ thị)',
            detail:
              'Thêm id của KO đối ứng và một loại quan hệ: related / part of / depends on / causes / mitigates / applies to. Các cạnh này phục vụ truy hồi nhiều bước; id sai sẽ làm mở rộng đi lệch hướng. Hãy dán UUID khi chưa có bộ chọn tìm kiếm và chạy kiểm tra xung đột trước khi gửi.',
          },
          {
            title: 'Người phụ trách và hiệu lực',
            detail: 'Đặt khoảng thời gian hiệu lực và người phụ trách; nếu muốn, có thể Nhận bản nháp AI rồi chỉnh sửa thủ công.',
          },
          {
            title: 'Lưu và gửi duyệt',
            detail:
              'Lưu dưới dạng bản nháp → tùy chọn Kiểm tra xung đột → Gửi duyệt kèm ghi chú. Tác giả có thể Rút lại khi mục vẫn đang chờ duyệt.',
          },
        ],
      },
      {
        title: 'Duyệt xuất bản và cho ngừng sử dụng',
        permission: 'review:approve',
        steps: [
          {
            title: 'Hàng đợi duyệt',
            detail:
              'Vận hành tri thức → Duyệt xuất bản; chuyển giữa các trạng thái chờ duyệt / đã duyệt / bị từ chối; mở một dòng trong trình biên tập KO.',
          },
          {
            title: 'Phê duyệt hoặc từ chối',
            detail:
              'Kiểm tra câu hỏi, câu trả lời, nguồn và quan hệ; xác nhận lại nếu xuất hiện cảnh báo xung đột. Chọn phê duyệt và xuất bản, hoặc từ chối kèm nhận xét. Sau khi xuất bản, tìm kiếm sẽ hiển thị huy hiệu KO và hỏi đáp có thể trích dẫn khi đã được lập chỉ mục.',
          },
          {
            title: 'Ngừng sử dụng',
            detail:
              'Các mục đã xuất bản có thể được đưa xuống với lý do cụ thể để chúng ngừng là tri thức chính thức có thể trích dẫn (xem trạng thái trên trang).',
          },
        ],
      },
    ],
  },
  {
    id: 'admin',
    title: 'Quản trị',
    icon: 'Setting',
    summary: 'Tổ chức, tài khoản, quyền hạn, kiểm toán, thuật ngữ, dữ liệu có cấu trúc và Ontology Studio.',
    permission: ADMIN_PERMISSIONS,
    topics: [
      {
        title: 'Đồng bộ danh bạ',
        permission: 'admin:directory',
        steps: [
          {
            title: 'Cấu hình nguồn',
            detail:
              'Mở Đồng bộ danh bạ, tạo mới hoặc chỉnh sửa một nguồn (WeCom / DingTalk / Weaver / Excel, v.v.), điền thông tin bí mật và ánh xạ trường rồi lưu.',
          },
          {
            title: 'Xem trước rồi áp dụng',
            detail:
              'Hãy luôn dùng Preview để xem các thay đổi thêm/cập nhật/vô hiệu đối với phòng ban và người dùng trước; chỉ Apply khi phần chênh lệch đã chính xác. Đừng bỏ qua bước xem trước trong production.',
          },
          {
            title: 'Lịch chạy và lịch sử',
            detail:
              'Thiết lập chu kỳ đồng bộ nếu cần. Mở một lần chạy trong lịch sử để xem chi tiết; sửa cấu hình theo lỗi rồi thử lại.',
          },
        ],
      },
      {
        title: 'Phòng ban và người dùng',
        permission: ['admin:dept', 'admin:user'],
        steps: [
          {
            title: 'Phòng ban',
            detail:
              'Phần Phòng ban duy trì cây tổ chức: tạo mới, đổi tên, di chuyển. Các trường được đồng bộ thường là chỉ đọc; hãy thay đổi ở hệ thống nguồn rồi đồng bộ lại.',
            permission: 'admin:dept',
          },
          {
            title: 'Người dùng',
            detail:
              'Phần Người dùng hiển thị tài khoản, phòng ban, vai trò và nhóm; khả năng bật/tắt và đăng nhập bằng mật khẩu phụ thuộc vào trang. Dữ liệu gốc của người dùng đã đồng bộ đến từ hệ thống nguồn.',
            permission: 'admin:user',
          },
        ],
      },
      {
        title: 'Nhóm và vai trò',
        permission: ['admin:group', 'admin:role'],
        steps: [
          {
            title: 'Nhóm',
            detail:
              'Nhóm dùng để tạo các đội làm việc xuyên phòng ban. Sau khi thêm thành viên, bạn có thể cấp quyền truy cập KB theo nhóm.',
            permission: 'admin:group',
          },
          {
            title: 'Vai trò',
            detail:
              'Vai trò dùng để bật/tắt quyền tính năng (chat:use, kb:create, admin:*, ...). Có thể gán vai trò hàng loạt. Các quyền quản trị không bao giờ được cấp ngầm; người dùng có thể cần làm mới hoặc đăng nhập lại để thấy menu mới.',
            permission: 'admin:role',
          },
        ],
      },
      {
        title: 'Nhật ký kiểm toán',
        permission: 'admin:audit',
        steps: [
          {
            title: 'Truy vấn',
            detail:
              'Mở Nhật ký kiểm toán và lọc theo hành động, loại tài nguyên/id, người thao tác và thời gian. Mở một dòng để xem chênh lệch trước/sau.',
          },
        ],
      },
      {
        title: 'Thuật ngữ (từ điển thực thể)',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Mục đích',
            detail:
              'Duy trì tên chuẩn + loại + bí danh. Cơ chế viết lại câu hỏi và tìm kiếm trên trang sẽ mở rộng truy vấn theo bí danh (ví dụ tên chuẩn “access control list”, bí danh “ACL”). Các thuật ngữ đang bật cũng có thể được đồng bộ vào từ đồng nghĩa OpenSearch cho nhánh BM25.',
          },
          {
            title: 'Mở và lọc',
            detail:
              'Quản trị → Thuật ngữ. Lọc theo từ khóa tên chuẩn, loại (thiết bị / quy trình / lỗi / điều khoản chính sách / thuật ngữ IT / khác) và trạng thái (bật/tắt), rồi tìm kiếm.',
          },
          {
            title: 'Tạo thuật ngữ',
            detail:
              'Thuật ngữ mới: tên chuẩn, loại, trạng thái, mô tả; có thể dán bí danh (phân tách bằng dấu phẩy hoặc xuống dòng) → Lưu. Hãy giữ tên là duy nhất và bí danh đầy đủ.',
          },
          {
            title: 'Duy trì bí danh',
            detail:
              'Tại cột Bí danh, nhập nội dung rồi Add; nhấp × trên một nhãn để xóa. Hộp thoại chỉnh sửa thường thay đổi tên/loại/mô tả/trạng thái, còn bí danh được chỉnh trực tiếp trên lưới.',
          },
          {
            title: 'Đồng bộ từ đồng nghĩa',
            detail:
              'Sau khi chỉnh sửa các thuật ngữ đang bật, nhấp Đồng bộ từ đồng nghĩa để ghi vào OpenSearch và nạp nóng. Các thuật ngữ bị tắt sẽ bị bỏ qua. Nếu bỏ qua bước này, từ đồng nghĩa trong chỉ mục sẽ bị lỗi thời.',
          },
          {
            title: 'Xem trước quan hệ và bản thể học',
            detail:
              'Thao tác hàng “Xem trước quan hệ” sẽ mở đồ thị lực: xanh dương = thuật ngữ, xanh lá = dữ liệu có cấu trúc, vàng = KO (khoảng 1 bước). Bản thể học là bản tóm tắt hợp đồng OWL chỉ đọc (TTL nằm trong repo; các thực thể nằm trong CSDL này).',
          },
        ],
      },
      {
        title: 'Dữ liệu có cấu trúc (bản sao id)',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Mục đích',
            detail:
              'Sao chép các đối tượng từ ERP/MES/QMS (thiết bị, lệnh công việc, phụ tùng hoặc các dòng dữ liệu miền chung) và ánh xạ `external_id` tới thuật ngữ hoặc KO. Phần thiết bị/mã trong “Khái niệm liên quan” của hỏi đáp và API resolve phụ thuộc vào đây. Đồng bộ chỉ cập nhật các bản sao, không tự động tạo thuật ngữ hay KO.',
          },
          {
            title: 'Miền và nguồn',
            detail:
              'Quản trị → Dữ liệu có cấu trúc. Chọn miền bên trái. «Nguồn mới» có thể chọn connector: MySQL, PostgreSQL, SQL Server, MongoDB, CSV, REST, hoặc không (thủ công). Mật khẩu dùng tên biến môi trường (ví dụ MES_MYSQL_PASSWORD), không lưu secret vào DB.',
          },
          {
            title: 'Bản ghi thủ công và tìm kiếm',
            detail:
              'Lọc theo nguồn và từ khóa. Ở các miền không phải thiết bị, New record cho phép điền external id, loại đối tượng, tiêu đề, v.v. Nhấp vào một dòng để mở bảng ánh xạ bên dưới.',
          },
          {
            title: 'Ánh xạ tới thuật ngữ / KO',
            detail:
              'Nhập id của thuật ngữ hoặc id của KO → Add mapping. Ánh xạ đúng sẽ cung cấp bí danh, mã định danh và tri thức liên quan cho phần hỏi đáp. Thông thường bạn sẽ dán UUID được sao chép từ danh sách Thuật ngữ hoặc KO.',
          },
          {
            title: 'Đồng bộ một nguồn',
            detail:
              'Chọn nguồn có connector trong bộ lọc → Đồng bộ nguồn để kéo vào bản sao cục bộ; hoặc cấu hình sync_interval_minutes trong meta để scheduler kéo định kỳ. Chi tiết: docs/ops/structured-connectors.md.',
          },
          {
            title: 'Resolve id (gỡ lỗi)',
            detail:
              'Biểu mẫu Resolve ở cuối trang: `object_type`, `external_id`, ... → Resolve rồi kiểm tra JSON. Tính năng này phục vụ QA ánh xạ, không dành cho nhân viên.',
          },
        ],
      },
      {
        title: 'Ontology Studio (ngữ nghĩa tổ chức)',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Mục đích',
            detail:
              'Ánh xạ bảng/collection MES thành bản nháp thực thể + thuộc tính, duyệt rồi xuất bản. Agent / Open API chỉ đọc bản đã publish. Mở Quản trị → Ontology Studio.',
          },
          {
            title: 'Kết nối CSDL và nhập schema',
            detail:
              'Bấm «Kết nối CSDL»: chọn MySQL / PostgreSQL / SQL Server / MongoDB → điền host/port/database (và Schema/auth source) hoặc dùng nguồn cấu trúc có sẵn → liệt kê bảng → chọn bảng/collection → xem trước → nhập vào bản nháp. MongoDB không có schema cố định; trường được suy ra từ tài liệu mẫu. Ưu tiên biến MES_*_PASSWORD.',
          },
          {
            title: 'Gợi ý, duyệt, xuất bản',
            detail:
              'Trên bản nháp có thể Generate suggestions cho nhãn/kiểu, rồi Approve (hoặc duyệt tất cả). Xuất bản sau khi ít nhất một thực thể được duyệt. Agent chỉ thấy mô hình published đang hiệu lực. Để khôi phục bản cũ, chọn phiên bản đã lưu trữ / published không active rồi bấm Khôi phục phiên bản này.',
          },
          {
            title: 'Bằng chứng và biểu thức tính',
            detail:
              'Chọn thực thể rồi gắn KO/tài liệu/chunk trong Bằng chứng; sau publish Agent đọc tóm tắt qua describe_ontology. Thuộc tính có thể khai báo biểu thức an toàn (vd a+b); get_object trả giá trị suy ra.',
          },
        ],
      },
      {
        title: 'Danh tính đa hệ thống',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Canonical và Identifier',
            detail:
              'Mở Quản trị → Danh tính đa hệ thống: tạo Canonical, gắn Identifier, xem tab Xung đột khi ID trỏ tới thực thể khác. Không ghi đè im lặng.',
          },
        ],
      },
      {
        title: 'Quy tắc và hành động',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Bảo trì rules và ActionType',
            detail:
              'Mở Quản trị → Quy tắc & Hành động: cấu hình quy tắc theo ưu tiên và loại hành động. Tắt hành động thì list_actions không còn thấy.',
          },
        ],
      },
    ],
  },
  {
    id: 'admin-agent',
    title: 'Trợ lý quản trị AI',
    icon: 'MagicStick',
    summary: 'Chạy các tác vụ quản trị có kiểm soát bằng ngôn ngữ tự nhiên: hiểu → làm rõ → lập kế hoạch → phê duyệt → thực thi.',
    permission: ADMIN_AGENT_PERMISSIONS,
    route: '/admin/agent',
    topics: [
      {
        title: 'Bắt đầu tác vụ',
        steps: [
          {
            title: 'Mở trợ lý',
            detail: 'Quản trị → Trợ lý quản trị AI. Các chip ví dụ có thể điền sẵn những lời nhắc phổ biến.',
          },
          {
            title: 'Mô tả ý định',
            detail:
              'Nêu mục tiêu trong một câu (ví dụ: “Bật đăng nhập bằng mật khẩu cho Zhang San”). Mô hình chỉ điền ý định và các trường; các bước ghi thay đổi do mã nguồn kiểm soát.',
          },
          {
            title: 'Làm rõ các trường bắt buộc',
            detail:
              'Nếu thiếu tên người hoặc tên nhóm, hệ thống sẽ hỏi thêm hoặc đưa danh sách ứng viên. Những tác vụ vượt quá quyền của bạn sẽ dừng lại ở đây.',
          },
        ],
      },
      {
        title: 'Phê duyệt và thực thi',
        steps: [
          {
            title: 'Xem kế hoạch',
            detail:
              'Sau bước làm rõ, một bản xem trước quy trình cố định sẽ xuất hiện (phân giải tên, kiểm tra hợp lệ, ứng viên). Hãy xác nhận từng đối tượng đích.',
          },
          {
            title: 'Rủi ro và phê duyệt',
            detail:
              'Các bước có rủi ro cao cần một ô xác nhận đã hiểu rủi ro. Phê duyệt có hiệu lực khoảng 30 phút, dùng một lần và chỉ cho người gửi yêu cầu. Hết thời gian thì phải bắt đầu lại.',
          },
          {
            title: 'Thực thi và báo cáo',
            detail:
              'Khi được phê duyệt, các bước sẽ chạy với cơ chế rollback nếu có lỗi và tạo báo cáo cuối cùng. Lịch sử có thể phát lại các sự kiện. Mật khẩu tạm thời sẽ được che đi.',
          },
          {
            title: 'Những việc trợ lý sẽ không làm',
            detail:
              'Trợ lý sẽ không xóa phòng ban/vai trò/người dùng, không thay đổi cấu hình mô hình hoặc truy xuất, và cũng không phát hành API key. Hãy dùng các trang quản trị chuyên biệt cho những việc đó.',
          },
        ],
      },
    ],
  },
  {
    id: 'platform',
    title: 'Kỹ thuật nền tảng',
    icon: 'Cpu',
    summary: 'Lập chỉ mục, mô hình, truy xuất, đánh giá và Open API (Quản trị → Kỹ thuật nền tảng).',
    permission: PLATFORM_PERMISSIONS,
    topics: [
      {
        title: 'Lập chỉ mục',
        permission: 'admin:index',
        steps: [
          {
            title: 'Kiểm tra công việc',
            detail:
              'Mở phần Lập chỉ mục để xem hàng đợi lập chỉ mục tài liệu, các lỗi và lần thử lại. Nếu hàng đợi tăng nhanh, hãy kiểm tra sức khỏe của worker / outbox trước.',
          },
          {
            title: 'Thử lại và xây dựng lại',
            detail:
              'Thử lại các tác vụ lỗi từ giao diện. Việc xây dựng lại toàn bộ từ cơ sở dữ liệu khá nặng, hãy thực hiện ngoài giờ cao điểm và không gửi lặp lại khi tiến trình vẫn đang chạy.',
          },
        ],
      },
      {
        title: 'Mô hình',
        permission: 'admin:model',
        steps: [
          {
            title: 'Kiểm tra và thăm dò',
            detail:
              'Phần Mô hình liệt kê các endpoint chat, embedding và rerank. Chạy kiểm tra sức khỏe để xác nhận khả năng kết nối và độ trễ.',
          },
          {
            title: 'Chuyển đổi mô hình chat',
            detail:
              'Thay đổi mô hình chat chính / dự phòng thường có hiệu lực ngay. Embedding/rerank thường chỉ để xem và thăm dò; thay đổi số chiều embedding cần làm theo hướng dẫn migration của vận hành, không chỉ đổi tên mô hình.',
          },
        ],
      },
      {
        title: 'Chiến lược truy xuất',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Điều chỉnh tham số',
            detail:
              'Phần Truy xuất cấu hình các bước recall, fusion và rerank. Hãy ghi lại các giá trị hiện tại, sau đó so sánh bằng đánh giá ngoại tuyến trước khi triển khai.',
          },
          {
            title: 'Mẫu trace',
            detail: 'Dùng trace/mẫu trên trang để kiểm tra recall và điểm số khi cần gỡ lỗi.',
          },
        ],
      },
      {
        title: 'Bộ dữ liệu và đánh giá ngoại tuyến',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Duy trì bộ dữ liệu',
            detail:
              'Các bộ dữ liệu đánh giá: tạo mới hoặc nhập câu hỏi chuẩn; chỉnh sửa tài liệu kỳ vọng/các điểm trả lời trên trang chi tiết.',
          },
          {
            title: 'Chạy đánh giá',
            detail:
              'Đánh giá ngoại tuyến: chọn một bộ dữ liệu và chiến lược, bắt đầu một lần chạy rồi mở chi tiết để xem tỷ lệ đạt và các lỗi.',
          },
          {
            title: 'So sánh chiến lược',
            detail:
              'Chọn 2-4 lần chạy đã hoàn tất trong danh sách rồi mở phần so sánh để quyết định có nên áp dụng chiến lược mới hay không.',
          },
        ],
      },
      {
        title: 'Open API',
        permission: 'admin:openapi',
        steps: [
          {
            title: 'Tạo ứng dụng',
            detail:
              'Open API → New app: đặt tên, gắn các principal (phòng ban/nhóm/vai trò) và chọn các kho tri thức được phép. Ứng dụng chỉ nhìn thấy phần giao cắt đó, không có đường vòng quản trị.',
          },
          {
            title: 'Phát hành API key',
            detail:
              'Trong trang chi tiết ứng dụng, tạo một key, sao chép một lần và lưu trữ an toàn. Cấu hình giới hạn theo phút và danh sách IP được phép.',
          },
          {
            title: 'Tích hợp và nhật ký',
            detail:
              'Dùng tab Hướng dẫn tích hợp cho REST/MCP; xem trước truy xuất trong phạm vi được phép; dùng nhật ký cuộc gọi cho 401/403/429. Hãy xoay vòng các key bị lộ và vô hiệu hóa những key cũ.',
          },
        ],
      },
    ],
  },
  {
    id: 'analytics',
    title: 'Phân tích',
    icon: 'DataAnalysis',
    summary: 'Dùng số liệu để quyết định nên bổ sung tri thức nào tiếp theo và kiểm tra xem hệ thống có đang khỏe mạnh hay không.',
    permission: 'analytics:view',
    route: '/analytics',
    topics: [
      {
        title: 'Đọc bảng điều khiển',
        steps: [
          {
            title: 'Mức sử dụng',
            detail: 'Theo dõi số câu hỏi, DAU và xu hướng; lọc theo ngày và kho tri thức để biết ai đang dùng gì.',
          },
          {
            title: 'Chất lượng và hiệu năng',
            detail:
              'Chất lượng phản ánh mức độ hài lòng, số lần từ chối và số lần bỏ sót; Hiệu năng phản ánh thời gian đến token đầu tiên và độ trễ theo từng giai đoạn. Khi chất lượng giảm, hãy bắt đầu từ khoảng trống tri thức và các câu hỏi thường xuyên chưa được trả lời.',
          },
          {
            title: 'Câu hỏi nóng và nội dung',
            detail:
              'Câu hỏi nóng hiển thị tần suất và số lần chưa được trả lời; Nội dung hiển thị các tài liệu lỗi và tình trạng trích dẫn. Hãy ưu tiên các thiếu hụt có tần suất cao để bổ sung tài liệu hoặc KO mới.',
          },
          {
            title: 'Mức sử dụng mô hình',
            detail: 'Lượng token theo tính năng và người dùng để phục vụ việc hoạch định chi phí và hạn mức.',
            permission: 'analytics:usage',
          },
        ],
      },
    ],
  },
]

export const MANUAL_FAQ: ManualFaq[] = [
  {
    question: 'Vì sao tôi không tìm thấy tài liệu trong phần tìm kiếm?',
    answer:
      'Các nguyên nhân phổ biến: ① bạn không có quyền vào kho hoặc tài liệu (bao gồm trường hợp trúng quy tắc deny); ② tài liệu vẫn đang được phân tích/lập chỉ mục; ③ quá trình xử lý đã thất bại. Hãy kiểm tra Status trên trang chi tiết kho hoặc hỏi quản trị viên của kho.',
  },
  {
    question: 'Tôi có thể tin vào câu trả lời của AI không?',
    answer:
      'Câu trả lời chỉ dùng nội dung mà bạn được phép truy cập và luôn kèm nguồn trích dẫn; nếu bằng chứng yếu, hệ thống sẽ từ chối hoặc thể hiện sự không chắc chắn. Với chính sách, tiền hoặc ngày tháng, hãy mở trích dẫn và kiểm tra lại bản gốc.',
    permission: 'chat:use',
  },
  {
    question: 'Người khác có nhìn thấy câu hỏi của tôi không?',
    answer:
      'Danh sách trò chuyện của bạn là riêng tư. Hệ thống vẫn lưu nhật ký hỏi đáp để phục vụ chất lượng; nhân sự có đúng quyền quản trị có thể dùng chúng cho hỗ trợ và phân tích, nhưng không ai khác nhìn thấy danh sách trò chuyện của bạn.',
    permission: 'chat:use',
  },
  {
    question: 'Sau khi tải lên bao lâu thì tệp có thể được tìm thấy?',
    answer:
      'Thường mất từ vài giây đến vài phút, tùy theo kích thước và hàng đợi. Hãy theo dõi Status trên trang chi tiết kho; nếu bị kẹt lâu, hãy nhờ quản trị viên kiểm tra phần Lập chỉ mục.',
    permission: 'doc:upload',
  },
  {
    question: 'Vì sao thiếu một menu hoặc nút bấm?',
    answer:
      'Menu phụ thuộc vào quyền tính năng theo vai trò; các thao tác trên tài liệu còn cần thêm ACL của KB/tài liệu. Hãy nhờ quản trị viên gán vai trò, hoặc nhờ quản trị viên của kho cấp quyền truy cập.',
  },
  {
    question: 'Tôi đã thu hồi quyền, sao họ vẫn còn hỏi được về nội dung đó?',
    answer:
      'Thay đổi ACL sẽ làm mất hiệu lực bộ nhớ đệm tìm kiếm và hỏi đáp sẽ kiểm tra lại quyền trong lúc tạo câu trả lời. Nếu tình trạng vẫn tiếp diễn, hãy kiểm tra các quyền khác theo nhóm/phòng ban hoặc xem quyền quản lý KB có đang bỏ qua một quy tắc deny ở mức tài liệu hay không.',
    permission: ADMIN_PERMISSIONS,
  },
  {
    question: 'Hàng đợi lập chỉ mục bị dồn hoặc có quá nhiều lỗi?',
    answer:
      'Mở phần Lập chỉ mục để xem chi tiết lỗi; xác nhận worker, outbox-dispatcher, OpenSearch và Qdrant đang khỏe mạnh. Hãy xử lý lại từng tài liệu hoặc thử lại theo lô; chỉ xây dựng lại toàn bộ khi thực sự cần và nên làm ngoài giờ cao điểm.',
    permission: 'admin:index',
  },
  {
    question: 'Open API trả về 401 / 403 / 429?',
    answer:
      '401: key sai hoặc đã bị vô hiệu; 403: IP không được phép hoặc không có quyền vào KB; 429: chạm giới hạn tần suất. Hãy kiểm tra key, các kho được phép, IP và hạn mức trên trang chi tiết ứng dụng, đồng thời xem nhật ký gọi API.',
    permission: 'admin:openapi',
  },
  {
    question: 'Bản xem trước đồng bộ danh bạ hiển thị số lượng vô hiệu rất lớn, có an toàn để áp dụng không?',
    answer:
      'Trước tiên hãy xác minh rằng các bộ lọc nguồn không bị cấu hình sai. Đồng bộ có ngưỡng an toàn cho tỷ lệ vô hiệu; hãy sửa dữ liệu ở hệ thống nguồn trước khi áp dụng để tránh vô hiệu hóa hàng loạt tài khoản.',
    permission: 'admin:directory',
  },
  {
    question: '“Khái niệm liên quan” đến từ đâu? Nếu sai thì sao?',
    answer:
      'Chúng đến từ các lần khớp thuật ngữ, ánh xạ id trong Dữ liệu có cấu trúc và các mục tri thức được liên kết. Nếu bị thiếu hoặc không khớp: thêm bí danh và Đồng bộ từ đồng nghĩa; ánh xạ đúng `external_id` trong Dữ liệu có cấu trúc; xuất bản hoặc liên kết các KO còn thiếu.',
    permission: 'chat:use',
  },
  {
    question: 'Tôi đã thêm quan hệ KO, tìm kiếm có thay đổi không?',
    answer:
      'Các KO đã xuất bản sẽ được lập chỉ mục và có thể được tăng điểm. Quan hệ sẽ cấp dữ liệu cho tuyến nhiều bước thứ ba khi graph recall được bật trong chiến lược truy xuất; các KO chưa xuất bản hoặc đã ngừng sử dụng sẽ không tham gia. Hãy xác minh bằng offline eval / graph-gate.',
    permission: ['ko:edit', 'admin:retrieval'],
  },
  {
    question: 'Tôi có chỉnh sửa bản thể học OWL ngay trên giao diện web không?',
    answer:
      'Không. Bản thể học trong ứng dụng chỉ để đọc. Hợp đồng lớp/quan hệ nằm trong `ontology/enterprise.ttl`; các thực thể được chỉnh trên các trang Thuật ngữ, KO và Dữ liệu có cấu trúc. Mọi thay đổi enum cần phía kỹ thuật xử lý cùng với việc kiểm tra TTL, và ở đây không có SPARQL.',
    permission: 'admin:retrieval',
  },
]
