# Kubernetes Security Framework with Kyverno

Framework Policy-as-Code cho Kubernetes sử dụng Kyverno, được xây dựng nhằm chuẩn hóa và tự động hóa việc áp dụng các chính sách bảo mật trên cluster.

Framework hiện gồm 30 policy thuộc các nhóm Pod Security, Image Security, Resource Governance, Metadata và Network Security. Mỗi policy được thiết kế kèm bộ test Positive, Negative, Boundary và Exception để kiểm tra logic trước khi triển khai thực tế.

Dự án hướng tới quy trình đầy đủ từ xây dựng policy, CLI Unit Test, Integration/E2E Test đến Audit, Enforce, Monitoring và Rollback.

> Trạng thái: Đã hoàn thiện 30 policy và CLI Unit Test. Hiện chuyển sang giai đoạn Integration/E2E testing trên Kubernetes cluster.