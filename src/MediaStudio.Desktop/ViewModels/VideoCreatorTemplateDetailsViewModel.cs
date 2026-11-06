using System.Collections.ObjectModel;
using System.IO;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;

namespace MediaStudio.Desktop.ViewModels;

public sealed record MediaSelectionSessionRequest(string TemplateId, string SelectionSessionId = "");

public sealed class VideoCreatorTemplateDetailsViewModel : ObservableObject
{
    private readonly Action _back;
    private readonly Func<Task>? _retry;

    public VideoCreatorTemplateDetailsViewModel(VideoTemplateDto template, Action back, Func<Task>? retry = null, Func<MediaSelectionSessionRequest, Task>? selectMedia = null)
    {
        ChooseMediaCommand = new AsyncRelayCommand(() => selectMedia?.Invoke(new MediaSelectionSessionRequest(template.TemplateId)) ?? Task.CompletedTask,
            _ => selectMedia is not null && MediaSelectionViewModel.IsEligible(Template));
        Template = template;
        TemplateId = template.TemplateId;
        AvailabilityStatus = template.AvailabilityStatus;
        DurationText = FormatDuration(template.DurationMs);
        AspectRatioText = ResolveAspectRatio(template);
        ResolutionText = template.Width > 0 && template.Height > 0
            ? $"{template.Width} × {template.Height}"
            : "";
        RequiredMediaSlots = Math.Max(0, template.RequiredMediaSlots);
        _back = back;
        _retry = retry;
        BackCommand = new RelayCommand(_ => _back());
        RetryCommand = new AsyncRelayCommand(() => _retry?.Invoke() ?? Task.CompletedTask,
            _ => _retry is not null);
        MediaSelectionRequest = new MediaSelectionSessionRequest(template.TemplateId);

        Scenes = new ObservableCollection<VideoTemplateSceneOverviewViewModel>(
            (template.Scenes ?? []).Select((scene, index) => new VideoTemplateSceneOverviewViewModel(index + 1, scene)));

        PosterPath = ResolveExistingLocalAsset(template.PosterPath, [".jpg", ".jpeg", ".png", ".webp", ".bmp"]);
        (PreviewUri, PreviewProblem) = ResolvePlayablePreview(template);
        PreviewAvailable = PreviewUri is not null;
        HasPoster = PosterPath is not null;
        PreviewStatus = PreviewAvailable ? "Video demo" : HasPoster ? "Ảnh poster" : "Chưa có preview";
        PreviewMessage = PreviewAvailable
            ? "Video demo do catalog cung cấp."
            : PreviewProblem ?? (HasPoster
                ? "Mẫu chưa có video xem trước. Ảnh poster được hiển thị ở trạng thái tĩnh."
                : "Mẫu chưa có video xem trước hoặc ảnh poster.");
        PreviewPlaceholderTitle = PreviewProblem is null
            ? "Mẫu chưa có video xem trước"
            : "Không thể mở video preview";
        PreviewPlaceholderDescription = PreviewProblem is null
            ? "Catalog chưa cung cấp poster hoặc video demo."
            : "Nguồn preview được khai báo nhưng không hợp lệ hoặc không thể truy cập.";
    }

    private VideoCreatorTemplateDetailsViewModel(
        string? templateId, string errorMessage, Action back, Func<Task>? retry)
    {
        TemplateId = templateId ?? "";
        DurationText = "—";
        AspectRatioText = "—";
        ResolutionText = "";
        RequiredMediaSlots = 0;
        PreviewStatus = "Catalog error";
        PreviewMessage = "";
        PreviewPlaceholderTitle = "Không thể mở mẫu";
        PreviewPlaceholderDescription = "";
        IsError = true;
        ErrorMessage = errorMessage;
        _back = back;
        _retry = retry;
        BackCommand = new RelayCommand(_ => _back());
        RetryCommand = new AsyncRelayCommand(() => _retry?.Invoke() ?? Task.CompletedTask,
            _ => _retry is not null);
        MediaSelectionRequest = new MediaSelectionSessionRequest(TemplateId);
        Scenes = [];
    }

    public static VideoCreatorTemplateDetailsViewModel CreateError(
        string? templateId, string errorMessage, Action back, Func<Task>? retry = null) =>
        new(templateId, errorMessage, back, retry);

    public VideoTemplateDto? Template { get; }
    public string TemplateId { get; } = "";
    public string AvailabilityStatus { get; } = "REFERENCE_ONLY";
    public string AvailabilityStatusText => AvailabilityStatus switch
    {
        "PILOT_RENDERABLE" when Template?.TemplateDefinitionVersion?.Contains("pilot", StringComparison.OrdinalIgnoreCase) == true
            => "Pilot · chưa phát hành",
        "PILOT_RENDERABLE" => "Pilot renderable",
        "READY_FOR_USERS" => "Ready for users",
        _ => "Reference only"
    };
    public string Name => Template?.Name ?? "Không thể mở mẫu";
    public string Category => Template?.Category ?? "";
    public bool HasCategory => !string.IsNullOrWhiteSpace(Category);
    public string CategoryOrUnavailableText => HasCategory ? Category : "Chưa cung cấp";
    public string Description => Template?.Description ?? "";
    public string DurationText { get; } = "";
    public string AspectRatioText { get; } = "";
    public string ResolutionText { get; } = "";
    public bool HasResolution => !string.IsNullOrWhiteSpace(ResolutionText);
    public string ResolutionOrUnavailableText => HasResolution ? ResolutionText : "Chưa cung cấp";
    public int RequiredMediaSlots { get; }
    public string RequiredMediaSlotsText => RequiredMediaSlots switch
    {
        1 => "1 vị trí media",
        > 1 => $"{RequiredMediaSlots} vị trí media",
        _ => "Số vị trí media chưa được cung cấp"
    };
    public string MediaSlotDetailMessage => IsDynamicFallDiary
        ? $"Definition {Template!.TemplateDefinitionVersion}: chọn từ 1 đến 36 media; hệ thống tự mở số vị trí theo lựa chọn."
        : IsAutumnLove40
            ? $"Definition {Template!.TemplateDefinitionVersion}: cần đúng 40 media theo thứ tự; thời lượng từng khung được ghi trên mỗi vị trí."
            : Template?.MediaSlotRequirements.Count > 0
                ? $"Definition {Template.TemplateDefinitionVersion}: {Template.MediaSlotRequirements.Count} slot đã khai báo."
                : "Chưa có slot definition đã xác minh.";
    public string MediaRulesMessage => IsDynamicFallDiary
        ? "Mỗi nhóm 9: media đầu làm nền (ảnh/video), tối đa 8 media sau phải là ảnh và được tự động tách nền, phủ lần lượt."
        : IsAutumnLove40
            ? "Mẫu dọc 9:16; cần đúng 40 media theo thứ tự. Ảnh chân dung tại khung phủ được tách nền; ảnh và video đều có thể dùng ở mọi vị trí."
            : Template?.MediaSlotRequirements.Count > 0
                ? DescribeMediaRules(Template.MediaSlotRequirements)
                : "Chưa có quy tắc media để áp dụng mẫu.";
    public ObservableCollection<VideoTemplateSceneOverviewViewModel> Scenes { get; }
    public bool HasScenes => Scenes.Count > 0;
    public string SceneStructureMessage => HasScenes
        ? IsDynamicFallDiary
            ? "Mẫu hỗ trợ tối đa 4 nhóm nền; số nhóm thực tế được tạo theo thứ tự media đã chọn."
            : IsAutumnLove40
                ? "Clip 11 giây; một số khung chồng thời gian để giữ đúng nhịp mẫu."
            : "Các phân đoạn bên dưới theo template definition; chúng không được ghép với vị trí media nếu catalog chưa khai báo mapping."
        : "Thông tin chi tiết phân đoạn chưa được catalog cung cấp.";
    public string? PosterPath { get; }
    public bool HasPoster { get; }
    public Uri? PreviewUri { get; }
    public string? PreviewProblem { get; }
    public bool PreviewAvailable { get; }
    public string PreviewStatus { get; }
    public string PreviewMessage { get; }
    public string PreviewPlaceholderTitle { get; }
    public string PreviewPlaceholderDescription { get; }
    public bool IsError { get; }
    private bool IsDynamicFallDiary => Template?.TemplateId == "fall-diary"
        && Template.TemplateDefinitionVersion is "0.6.0-dynamic-batches" or "0.7.0-reference-timing"
            or "0.8.0-intro-title" or "0.9.0-reference-overlays";
    private bool IsAutumnLove40 => Template?.TemplateId == "autumn-love-40"
        && Template.TemplateDefinitionVersion == "1.0.0-reference-sequence";
    public string ErrorMessage { get; } = "";
    public MediaSelectionSessionRequest MediaSelectionRequest { get; }
    public string MediaSelectionUnavailableMessage => MediaSelectionViewModel.IsEligible(Template)
        ? IsDynamicFallDiary
            ? "Chọn từ 1 đến 36 media theo thứ tự; nền và ảnh phủ sẽ tự gán."
            : IsAutumnLove40
                ? "Chọn đúng 40 ảnh/video theo thứ tự của mẫu; nếu một mục chưa tương thích, trang chọn media sẽ nêu rõ vị trí và lý do."
            : "Chọn media và gán vào các vị trí đã xác minh. Chưa tạo project hoặc render."
        : "Mẫu chưa có slot definition đã xác minh nên chưa thể áp dụng.";
    public AsyncRelayCommand ChooseMediaCommand { get; } = new(() => Task.CompletedTask, _ => false);
    public RelayCommand BackCommand { get; }
    public AsyncRelayCommand RetryCommand { get; }

    private static string DescribeMediaRules(IReadOnlyCollection<VideoTemplateMediaSlotRequirementDto> slots)
    {
        var kinds = slots.SelectMany(slot => slot.AllowedMediaKinds).Distinct(StringComparer.OrdinalIgnoreCase)
            .Select(kind => kind switch { "image" => "ảnh", "video" => "video", "audio" => "âm thanh", _ => kind });
        var reuse = slots.All(slot => slot.ReusePolicy == "allow")
            ? "có thể dùng lại media theo policy"
            : "một số slot yêu cầu media riêng";
        var required = slots.Count(slot => slot.Required || slot.MissingSlotPolicy == "error");
        return $"{string.Join("/", kinds)} · {required} slot bắt buộc · {reuse}.";
    }

    private static string FormatDuration(int milliseconds)
    {
        if (milliseconds <= 0) return "Chưa cung cấp";
        var duration = TimeSpan.FromMilliseconds(Math.Max(0, milliseconds));
        return duration.TotalHours >= 1
            ? duration.ToString(@"hh\:mm\:ss")
            : duration.ToString(@"mm\:ss");
    }

    private static string ResolveAspectRatio(VideoTemplateDto template)
    {
        if (!string.IsNullOrWhiteSpace(template.AspectRatio)) return template.AspectRatio;
        if (template.Width <= 0 || template.Height <= 0) return "Chưa cung cấp";
        var divisor = GreatestCommonDivisor(template.Width, template.Height);
        return $"{template.Width / divisor}:{template.Height / divisor}";
    }

    private static int GreatestCommonDivisor(int left, int right)
    {
        while (right != 0) (left, right) = (right, left % right);
        return Math.Max(1, left);
    }

    private static string? ResolveExistingLocalAsset(string? source, string[] supportedExtensions)
    {
        if (string.IsNullOrWhiteSpace(source)) return null;
        try
        {
            var path = ResolveLocalPath(source);
            if (path is null || !File.Exists(path)) return null;
            return supportedExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase) ? path : null;
        }
        catch (Exception error) when (error is ArgumentException or IOException or UnauthorizedAccessException
                                      or NotSupportedException or UriFormatException)
        {
            return null;
        }
    }

    private static (Uri? PreviewUri, string? Problem) ResolvePlayablePreview(VideoTemplateDto template)
    {
        if (!template.PreviewAvailable) return (null, null);
        if (string.IsNullOrWhiteSpace(template.PreviewSource))
            return (null, "Catalog đánh dấu có video preview nhưng chưa cung cấp đường dẫn.");

        try
        {
            var path = ResolveLocalPath(template.PreviewSource);
            if (path is null)
                return (null, "Video preview từ URL/backend chưa có endpoint hoặc cơ chế xác thực được cấu hình.");
            var extension = Path.GetExtension(path);
            if (!new[] { ".mp4", ".wmv", ".avi", ".mov", ".m4v" }
                .Contains(extension, StringComparer.OrdinalIgnoreCase))
                return (null, $"Định dạng preview “{extension}” chưa được hỗ trợ.");
            if (!File.Exists(path)) return (null, "Không tìm thấy file video preview được catalog khai báo.");
            return (new Uri(path, UriKind.Absolute), null);
        }
        catch (Exception error) when (error is ArgumentException or IOException or UnauthorizedAccessException
                                      or NotSupportedException or UriFormatException)
        {
            return (null, "Không thể truy cập file video preview được catalog khai báo.");
        }
    }

    private static string? ResolveLocalPath(string source)
    {
        if (Uri.TryCreate(source, UriKind.Absolute, out var uri))
            return uri.IsFile ? Path.GetFullPath(uri.LocalPath) : null;
        return Path.GetFullPath(source);
    }
}

public sealed class VideoTemplateSceneOverviewViewModel(int index, VideoTemplateSceneDto scene)
{
    public int Index { get; } = index;
    public string Name { get; } = scene.Name;
    public string DurationText { get; } = scene.DurationMs > 0
        ? TimeSpan.FromMilliseconds(scene.DurationMs).TotalSeconds.ToString("0.##") + " giây"
        : "Thời lượng chưa khai báo";
}
