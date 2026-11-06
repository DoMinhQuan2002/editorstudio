using System.IO;
using System.Net.Http;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;
using SkiaSharp;
using Svg.Skia;

namespace MediaStudio.Desktop.ViewModels;

public sealed class VectorizeToolViewModel : ImageToolPageViewModel
{
    private static readonly Brush CheckerboardBrush = CreateCheckerboardBrush();
    private readonly IImagePicker _imagePicker;
    private readonly VectorizationJobService? _jobService;
    private string? _sourcePath;
    private bool _isProcessing;
    private bool _isCompareMode;
    private bool _smartHasResult;
    private bool _contourHasResult;
    private string _selectedVectorMethod = "smart_reconstruction";
    private string _qualityMode = "auto";
    private int _colorCount = 8;
    private int _detail = 50;
    private bool _removeBackground = true;
    private string _outputMode = "cutout";
    private string _textMode = "outlined";
    private string _previewBackground = "checkerboard";
    private string _smartStateText = "Chưa chạy";
    private string _contourStateText = "Chưa chạy";
    private int _smartProgress;
    private int _contourProgress;
    private int _singleProgress;
    private double _zoomFactor = 1;
    private double _panX;
    private double _panY;
    private byte[]? _smartSvgBytes;
    private byte[]? _contourSvgBytes;
    private BitmapImage? _smartPreviewImage;
    private BitmapImage? _contourPreviewImage;
    private int? _smartPathCount;
    private int? _contourPathCount;
    private readonly bool _contourExperimentalEnabled;
    private readonly bool _contourDependencyAvailable;
    private readonly string? _contourDependencyVersion;

    public VectorizeToolViewModel(
        IImagePicker imagePicker,
        MediaStudioApiClient? apiClient,
        BackendHealth? backendHealth = null)
        : base(imagePicker, "hoa-cuc.png", "1200 × 1200 px  ·  486 KB")
    {
        _imagePicker = imagePicker;
        _jobService = apiClient is null ? null : new VectorizationJobService(apiClient);
        _sourcePath = SelectedImagePath;
        _contourExperimentalEnabled = backendHealth?.ContourExperimentalEnabled == true;
        _contourDependencyAvailable = backendHealth?.ContourDependencyAvailable == true;
        _contourDependencyVersion = backendHealth?.ContourDependencyVersion;

        RunCommand = new AsyncRelayCommand(RunSelectedEngineAsync, CanRunSingle);
        CompareCommand = new AsyncRelayCommand(RunCompareAsync, CanRunCompare);
        SaveResultCommand = new AsyncRelayCommand(SaveSelectedResultAsync, _ => CanSaveSelected);
        SavePngCommand = new AsyncRelayCommand(SavePngAsync, _ => CanSaveSelected);
        SaveSmartResultCommand = new AsyncRelayCommand(SaveSmartResultAsync, _ => _smartHasResult && !IsProcessing);
        SaveContourResultCommand = new AsyncRelayCommand(SaveContourResultAsync, _ => _contourHasResult && !IsProcessing);
        SaveBothCommand = new AsyncRelayCommand(SaveBothAsync, _ => _smartHasResult && _contourHasResult && !IsProcessing);
        ReturnToSingleCommand = new RelayCommand(_ => IsCompareMode = false);
        SetZoomCommand = new RelayCommand(SetZoom);
    }

    public bool ContourExperimentalEnabled => _contourExperimentalEnabled;
    public bool ContourDependencyAvailable => _contourDependencyAvailable;
    public bool ContourOptionEnabled => ContourReady;
    public bool UsesForegroundAlpha => false;
    public BitmapSource? VectorSourcePreviewImage => PreviewImage;
    public string SourcePreviewTitle => "Ảnh gốc";
    public string ForegroundAlphaStatusText => "Nền được nhận diện tự động";
    public bool ContourReady => _contourExperimentalEnabled && _contourDependencyAvailable;
    public bool IsSingleMode => !IsCompareMode;
    public string WorkspaceCaption => IsCompareMode ? "So sánh hai phương pháp" : "So sánh gốc / vector";
    public bool IsCompareMode
    {
        get => _isCompareMode;
        private set
        {
            if (SetProperty(ref _isCompareMode, value))
            {
                OnPropertyChanged(nameof(IsSingleMode));
                OnPropertyChanged(nameof(CompareButtonLabel));
                OnPropertyChanged(nameof(WorkspaceCaption));
            }
        }
    }

    public string SelectedVectorMethod
    {
        get => _selectedVectorMethod;
        set
        {
            if (value == "contour_preserving" && !ContourReady)
            {
                OnPropertyChanged(nameof(SelectedVectorMethod));
                return;
            }
            if (value is not ("smart_reconstruction" or "contour_preserving")) return;
            if (SetProperty(ref _selectedVectorMethod, value))
            {
                OnPropertyChanged(nameof(SelectedMethodTitle));
                OnPropertyChanged(nameof(SelectedMethodDescription));
                OnPropertyChanged(nameof(SelectedResultPreviewImage));
                OnPropertyChanged(nameof(SelectedResultSummary));
                OnPropertyChanged(nameof(CanSaveSelected));
                NotifyCommands();
            }
        }
    }

    public string SelectedMethodTitle => IsCutoutMode ? "Tách logo khỏi nền" : "Vector màu theo lớp";

    public string SelectedMethodDescription => IsCutoutMode
        ? "Tự nhận diện đâu là logo, đâu là nền rồi cắt bỏ nền. Giữ nguyên 100% màu sắc, chi tiết và kích thước ảnh gốc. Xuất PNG trong suốt hoặc SVG."
        : "Vẽ lại logo thành các lớp màu vector có chuyển sắc. Phóng to không vỡ, nhưng màu và chi tiết chỉ gần giống ảnh gốc.";

    public string ContourAvailabilityMessage => !_contourExperimentalEnabled
        ? "Contour đang tắt. Đặt MEDIASTUDIO_CONTOUR_EXPERIMENTAL=1 trước khi khởi động MediaStudio; trạng thái được đọc lúc backend khởi chạy."
        : !_contourDependencyAvailable
            ? $"Contour chưa sẵn sàng: cần scikit-image 0.26.0{(_contourDependencyVersion is null ? "" : $" (đang có {_contourDependencyVersion})")}. Smart Reconstruction vẫn dùng được."
            : "Contour đang bật cho thử nghiệm local; Smart Reconstruction vẫn là lựa chọn mặc định.";

    public string QualityMode
    {
        get => _qualityMode;
        set
        {
            if (value is not ("auto" or "fast" or "quality" or "ai")) return;
            if (!IsProcessing && SetProperty(ref _qualityMode, value)) ClearResults("Chế độ chất lượng đã đổi · hãy chạy lại để cập nhật SVG.");
        }
    }

    public string TextMode
    {
        get => _textMode;
        set
        {
            if (value is not ("outlined" or "editable")) return;
            if (!IsProcessing && SetProperty(ref _textMode, value)) ClearResults("Kiểu chữ đã đổi · hãy chạy lại để cập nhật SVG.");
        }
    }

    public int ColorCount
    {
        get => _colorCount;
        set
        {
            var clamped = Math.Clamp(value, 2, 24);
            if (!IsProcessing && SetProperty(ref _colorCount, clamped)) ClearResults("Số màu đã đổi · bấm chạy lại để cập nhật SVG.");
        }
    }

    public int Detail
    {
        get => _detail;
        set
        {
            var clamped = Math.Clamp(value, 0, 100);
            if (!IsProcessing && SetProperty(ref _detail, clamped)) ClearResults("Mức chi tiết đã đổi · bấm chạy lại để cập nhật SVG.");
        }
    }

    public string OutputMode
    {
        get => _outputMode;
        set
        {
            if (value is not ("cutout" or "vector") || IsProcessing) return;
            if (SetProperty(ref _outputMode, value))
            {
                OnPropertyChanged(nameof(IsCutoutMode));
                OnPropertyChanged(nameof(IsVectorMode));
                OnPropertyChanged(nameof(SelectedMethodTitle));
                OnPropertyChanged(nameof(SelectedMethodDescription));
                OnPropertyChanged(nameof(RunButtonLabel));
                ClearResults("Đã đổi kiểu xuất · bấm chạy lại để cập nhật kết quả.");
            }
        }
    }

    public bool IsCutoutMode
    {
        get => _outputMode == "cutout";
        set { if (value) OutputMode = "cutout"; }
    }

    public bool IsVectorMode
    {
        get => _outputMode == "vector";
        set { if (value) OutputMode = "vector"; }
    }

    public bool RemoveBackground
    {
        get => _removeBackground;
        set
        {
            if (!IsProcessing && SetProperty(ref _removeBackground, value)) ClearResults("Tùy chọn nền đã đổi · bấm chạy lại để cập nhật SVG.");
        }
    }

    public string PreviewBackground
    {
        get => _previewBackground;
        set
        {
            if (value is not ("white" or "black" or "checkerboard")) return;
            if (SetProperty(ref _previewBackground, value)) OnPropertyChanged(nameof(PreviewBackgroundBrush));
        }
    }

    public Brush PreviewBackgroundBrush => PreviewBackground switch
    {
        "white" => Brushes.White,
        "black" => Brushes.Black,
        _ => CheckerboardBrush
    };

    public double ZoomFactor
    {
        get => _zoomFactor;
        set
        {
            var bounded = Math.Clamp(double.IsFinite(value) ? value : 1, .1, 8);
            if (SetProperty(ref _zoomFactor, bounded)) OnPropertyChanged(nameof(ZoomLabel));
        }
    }

    public double PanX
    {
        get => _panX;
        set => SetProperty(ref _panX, Math.Clamp(double.IsFinite(value) ? value : 0, -1.5, 1.5));
    }

    public double PanY
    {
        get => _panY;
        set => SetProperty(ref _panY, Math.Clamp(double.IsFinite(value) ? value : 0, -1.5, 1.5));
    }

    public string ZoomLabel => $"{ZoomFactor:P0}";
    public string SmartStateText { get => _smartStateText; private set => SetProperty(ref _smartStateText, value); }
    public string ContourStateText { get => _contourStateText; private set => SetProperty(ref _contourStateText, value); }
    public int SmartProgress { get => _smartProgress; private set => SetProperty(ref _smartProgress, Math.Clamp(value, 0, 100)); }
    public int ContourProgress { get => _contourProgress; private set => SetProperty(ref _contourProgress, Math.Clamp(value, 0, 100)); }
    public int SingleProgress { get => _singleProgress; private set => SetProperty(ref _singleProgress, Math.Clamp(value, 0, 100)); }
    public bool IsProcessing
    {
        get => _isProcessing;
        private set
        {
            if (SetProperty(ref _isProcessing, value))
            {
                OnPropertyChanged(nameof(IsOptionsEnabled));
                OnPropertyChanged(nameof(RunButtonLabel));
                OnPropertyChanged(nameof(CanSaveSelected));
                NotifyCommands();
                OpenImageCommand.NotifyCanExecuteChanged();
            }
        }
    }

    public bool IsOptionsEnabled => !IsProcessing;
    public bool SmartHasResult => _smartHasResult;
    public bool ContourHasResult => _contourHasResult;
    public bool SmartHasPreview => SmartPreviewImage is not null;
    public bool ContourHasPreview => ContourPreviewImage is not null;
    public bool SmartHasNoPreview => !_smartHasResult || SmartPreviewImage is null;
    public bool ContourHasNoPreview => !_contourHasResult || ContourPreviewImage is null;
    public bool ShowSingleResultPreview => SelectedResultPreviewImage is not null;
    public bool ShowSingleResultPlaceholder => HasImportedImage && SelectedResultPreviewImage is null;
    public BitmapImage? SmartPreviewImage { get => _smartPreviewImage; private set => SetPreview(ref _smartPreviewImage, value, nameof(SmartPreviewImage)); }
    public BitmapImage? ContourPreviewImage { get => _contourPreviewImage; private set => SetPreview(ref _contourPreviewImage, value, nameof(ContourPreviewImage)); }
    public BitmapImage? SelectedResultPreviewImage => SelectedVectorMethod == "contour_preserving" ? ContourPreviewImage : SmartPreviewImage;
    public string SelectedResultSummary => SelectedVectorMethod == "contour_preserving" ? ContourResultSummary : SmartResultSummary;
    public string SmartResultSummary => _smartHasResult ? $"{_smartPathCount ?? 0:N0} đường · SVG" : "Chưa có kết quả";
    public string ContourResultSummary => _contourHasResult ? $"{_contourPathCount ?? 0:N0} đường · SVG" : "Chưa có kết quả";
    public string CompareButtonLabel => _smartHasResult || _contourHasResult ? "Chạy lại so sánh" : "So sánh hai phương pháp";
    public string RunButtonLabel => IsProcessing
        ? IsCutoutMode ? "Đang tách nền…" : "Đang vẽ vector…"
        : IsCutoutMode ? "Tách logo khỏi nền" : "Chuyển sang vector";
    public AsyncRelayCommand SaveResultCommand { get; }
    public AsyncRelayCommand SavePngCommand { get; }
    public AsyncRelayCommand SaveSmartResultCommand { get; }
    public AsyncRelayCommand SaveContourResultCommand { get; }
    public AsyncRelayCommand SaveBothCommand { get; }
    public AsyncRelayCommand CompareCommand { get; }
    public RelayCommand ReturnToSingleCommand { get; }
    public RelayCommand SetZoomCommand { get; }

    public bool CanSaveSelected => !IsProcessing && (SelectedVectorMethod == "contour_preserving" ? _contourHasResult : _smartHasResult);

    protected override bool CanOpenImage => !IsProcessing;
    protected override void OnImageAvailabilityChanged() => NotifyCommands();

    protected override void OnImageChanged(int width, int height)
    {
        ClearResults();
        StatusMessage = _jobService is null
            ? "Python backend chưa kết nối. Hãy khởi động lại MediaStudio khi backend sẵn sàng."
            : "Ảnh đã sẵn sàng · bấm chuyển để tạo SVG.";
        ZoomFactor = 1;
        PanX = PanY = 0;
        _sourcePath = SelectedImagePath;
        OnPropertyChanged(nameof(UsesForegroundAlpha));
        OnPropertyChanged(nameof(VectorSourcePreviewImage));
        OnPropertyChanged(nameof(SourcePreviewTitle));
        OnPropertyChanged(nameof(ForegroundAlphaStatusText));
    }

    private async Task<ImportedAsset> ImportCurrentSourceAsync(string sourcePath)
    {
        if (_jobService is null) throw new InvalidOperationException("Vectorization backend chưa sẵn sàng.");
        return await _jobService.ImportSourceAsync(sourcePath);
    }

    private bool CanRunSingle(object? _) => _jobService is not null && HasImportedImage && !IsProcessing &&
        (SelectedVectorMethod != "contour_preserving" || ContourReady);

    private bool CanRunCompare(object? _) => _jobService is not null && HasImportedImage && !IsProcessing && ContourReady;

    private async Task RunSelectedEngineAsync()
    {
        if (_jobService is null || SelectedImagePath is null) return;
        IsCompareMode = false;
        IsProcessing = true;
        var method = SelectedVectorMethod;
        ResetEngineResult(method);
        SingleProgress = 0;
        StatusMessage = UsesForegroundAlpha
            ? "Đang nhập ảnh RGBA đã chỉnh alpha vào backend local."
            : "Đang nhập ảnh vào backend local.";
        try
        {
            var asset = await ImportCurrentSourceAsync(SelectedImagePath);
            await RunEngineAsync(asset.AssetId, method, false);
        }
        catch (Exception error)
        {
            SetEngineFailure(method, FormatError(error));
        }
        finally
        {
            IsProcessing = false;
            OnPropertyChanged(nameof(RunButtonLabel));
        }
    }

    private async Task RunCompareAsync()
    {
        if (_jobService is null || SelectedImagePath is null || !ContourReady) return;
        IsCompareMode = true;
        IsProcessing = true;
        ClearResults();
        SmartStateText = "Đang chờ";
        ContourStateText = "Đang chờ";
        StatusMessage = UsesForegroundAlpha
            ? "Đang nhập ảnh RGBA đã chỉnh alpha để dùng chung cho cả hai engine."
            : "Đang nhập một ảnh nguồn duy nhất để dùng chung cho cả hai engine.";
        try
        {
            var asset = await ImportCurrentSourceAsync(SelectedImagePath);
            await RunEngineAsync(asset.AssetId, "smart_reconstruction", true);
            await RunEngineAsync(asset.AssetId, "contour_preserving", true);

            if (_smartHasResult && _contourHasResult)
                StatusMessage = "So sánh hoàn tất · cả hai SVG dùng cùng ảnh nguồn và cùng thiết lập.";
            else if (_smartHasResult || _contourHasResult)
                StatusMessage = "So sánh một phần · giữ lại kết quả engine thành công; engine còn lại có thể chạy lại riêng.";
            else
                StatusMessage = "Cả hai engine đều chưa tạo được kết quả. Xem trạng thái từng panel để biết chi tiết.";
        }
        catch (Exception error)
        {
            var message = FormatError(error);
            SmartStateText = ContourStateText = $"Không bắt đầu được · {message}";
            StatusMessage = $"Không thể nhập ảnh nguồn cho Compare: {message}";
        }
        finally
        {
            IsProcessing = false;
        }
    }

    private async Task RunEngineAsync(string assetId, string method, bool compare)
    {
        SetEngineState(method, "Đang xếp job", 0);
        try
        {
            var result = await _jobService!.RunAsync(
                assetId,
                method,
                QualityMode,
                TextMode,
                job => SetEngineProgress(method, job),
                colorCount: ColorCount,
                detail: Detail,
                removeBackground: RemoveBackground,
                outputMode: OutputMode);

            StoreEngineResult(result);
            SetEngineState(method, "SVG đã tạo · đang render preview", 100);
            try
            {
                var preview = await Task.Run(() => RenderSvgPreview(result.SvgBytes));
                if (method == "smart_reconstruction") SmartPreviewImage = preview;
                else ContourPreviewImage = preview;
                SetEngineState(method, $"Hoàn tất · {result.Job.ResultPaths ?? 0:N0} đường · {FormatSize(result.SvgBytes.LongLength)}", 100);
            }
            catch (Exception renderError) when (renderError is InvalidDataException or InvalidOperationException or ArgumentException)
            {
                SetEngineState(method, $"SVG đã tạo nhưng preview lỗi: {renderError.Message}", 100);
            }
            OnPropertyChanged(nameof(SelectedResultPreviewImage));
            OnPropertyChanged(nameof(ShowSingleResultPreview));
            OnPropertyChanged(nameof(ShowSingleResultPlaceholder));
            OnPropertyChanged(nameof(SelectedResultSummary));
            OnPropertyChanged(nameof(CompareButtonLabel));
            OnPropertyChanged(nameof(SmartHasNoPreview));
            OnPropertyChanged(nameof(ContourHasNoPreview));
            NotifyCommands();
        }
        catch (Exception error)
        {
            SetEngineFailure(method, FormatError(error));
            if (!compare) StatusMessage = $"Không thể chạy {EngineName(method)}: {FormatError(error)}";
        }
    }

    private void StoreEngineResult(VectorizationRunResult result)
    {
        if (result.VectorMethod == "smart_reconstruction")
        {
            _smartSvgBytes = result.SvgBytes;
            _smartHasResult = true;
            _smartPathCount = result.Job.ResultPaths;
            OnPropertyChanged(nameof(SmartHasResult));
            OnPropertyChanged(nameof(SmartResultSummary));
        }
        else
        {
            _contourSvgBytes = result.SvgBytes;
            _contourHasResult = true;
            _contourPathCount = result.Job.ResultPaths;
            OnPropertyChanged(nameof(ContourHasResult));
            OnPropertyChanged(nameof(ContourResultSummary));
        }
    }

    private void ResetEngineResult(string method)
    {
        if (method == "smart_reconstruction")
        {
            _smartSvgBytes = null;
            _smartHasResult = false;
            _smartPathCount = null;
            SmartPreviewImage = null;
            SmartStateText = "Đang chạy Smart Reconstruction";
            SmartProgress = 0;
            OnPropertyChanged(nameof(SmartHasResult));
            OnPropertyChanged(nameof(SmartResultSummary));
        }
        else
        {
            _contourSvgBytes = null;
            _contourHasResult = false;
            _contourPathCount = null;
            ContourPreviewImage = null;
            ContourStateText = "Đang chạy Contour-Preserving";
            ContourProgress = 0;
            OnPropertyChanged(nameof(ContourHasResult));
            OnPropertyChanged(nameof(ContourResultSummary));
        }
        OnPropertyChanged(nameof(SelectedResultPreviewImage));
        OnPropertyChanged(nameof(ShowSingleResultPreview));
        OnPropertyChanged(nameof(ShowSingleResultPlaceholder));
        OnPropertyChanged(nameof(SelectedResultSummary));
        OnPropertyChanged(nameof(SmartHasNoPreview));
        OnPropertyChanged(nameof(ContourHasNoPreview));
        NotifyCommands();
    }

    private void ClearResults(string? status = null)
    {
        _smartSvgBytes = null;
        _contourSvgBytes = null;
        _smartHasResult = false;
        _contourHasResult = false;
        _smartPathCount = null;
        _contourPathCount = null;
        SmartPreviewImage = null;
        ContourPreviewImage = null;
        SmartProgress = ContourProgress = SingleProgress = 0;
        SmartStateText = "Chưa chạy";
        ContourStateText = ContourReady ? "Chưa chạy" : "Contour chưa sẵn sàng";
        OnPropertyChanged(nameof(SmartHasResult));
        OnPropertyChanged(nameof(ContourHasResult));
        OnPropertyChanged(nameof(SmartResultSummary));
        OnPropertyChanged(nameof(ContourResultSummary));
        OnPropertyChanged(nameof(SelectedResultPreviewImage));
        OnPropertyChanged(nameof(ShowSingleResultPreview));
        OnPropertyChanged(nameof(ShowSingleResultPlaceholder));
        OnPropertyChanged(nameof(SelectedResultSummary));
        OnPropertyChanged(nameof(CompareButtonLabel));
        OnPropertyChanged(nameof(SmartHasNoPreview));
        OnPropertyChanged(nameof(ContourHasNoPreview));
        NotifyCommands();
        if (status is not null) StatusMessage = status;
    }

    private void SetEngineProgress(string method, BackendJob job)
    {
        var label = $"{job.State}: {job.Stage}";
        if (job.IsIndeterminate)
            label += " · đang xử lý";
        else
            label += $" · {Math.Clamp(job.Progress, 0, 100)}%";
        SetEngineState(method, label, job.Progress);
        SingleProgress = job.Progress;
        StatusMessage = $"{EngineName(method)} · {job.Stage}";
    }

    private void SetEngineState(string method, string state, int progress)
    {
        if (method == "smart_reconstruction")
        {
            SmartStateText = state;
            SmartProgress = progress;
        }
        else
        {
            ContourStateText = state;
            ContourProgress = progress;
        }
    }

    private void SetEngineFailure(string method, string message)
    {
        SetEngineState(method, $"Thất bại · {message}", 0);
        StatusMessage = $"{EngineName(method)} thất bại · {message}";
    }

    private async Task SaveSelectedResultAsync() => await SaveEngineResultAsync(SelectedVectorMethod);
    private async Task SaveSmartResultAsync() => await SaveEngineResultAsync("smart_reconstruction");
    private async Task SaveContourResultAsync() => await SaveEngineResultAsync("contour_preserving");

    private async Task<bool> SaveEngineResultAsync(string method)
    {
        var bytes = method == "smart_reconstruction" ? _smartSvgBytes : _contourSvgBytes;
        if (bytes is null)
        {
            StatusMessage = $"Chưa có SVG {EngineName(method)} để lưu.";
            return false;
        }

        var suffix = IsCutoutMode ? "logo" : "vector";
        var defaultName = $"{Path.GetFileNameWithoutExtension(InputFileName)}_{suffix}.svg";
        var path = _imagePicker.PickSavePath(defaultName, "SVG");
        if (string.IsNullOrWhiteSpace(path)) return false;
        if (!path.EndsWith(".svg", StringComparison.OrdinalIgnoreCase)) path = Path.ChangeExtension(path, ".svg");
        if (_sourcePath is not null && string.Equals(Path.GetFullPath(path), Path.GetFullPath(_sourcePath), StringComparison.OrdinalIgnoreCase))
        {
            StatusMessage = "Không thể lưu SVG lên trên ảnh nguồn. Hãy chọn một tệp đích khác.";
            return false;
        }

        try
        {
            await File.WriteAllBytesAsync(path, bytes);
            StatusMessage = $"Đã lưu SVG {EngineName(method)}: {Path.GetFileName(path)}";
            return true;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            StatusMessage = $"Không thể lưu SVG {EngineName(method)}: {error.Message}";
            return false;
        }
    }

    private async Task SavePngAsync()
    {
        if (_smartSvgBytes is null) { StatusMessage = "Chưa có kết quả để lưu."; return; }
        var path = _imagePicker.PickSavePath($"{Path.GetFileNameWithoutExtension(InputFileName)}_logo.png", "PNG");
        if (string.IsNullOrWhiteSpace(path)) return;
        if (!path.EndsWith(".png", StringComparison.OrdinalIgnoreCase)) path = Path.ChangeExtension(path, ".png");
        try
        {
            var text = System.Text.Encoding.UTF8.GetString(_smartSvgBytes);
            var marker = "data:image/png;base64,";
            var start = text.IndexOf(marker, StringComparison.Ordinal);
            byte[] png;
            if (start >= 0)
            {
                start += marker.Length;
                var end = text.IndexOf('"', start);
                png = Convert.FromBase64String(text[start..end]);
            }
            else
            {
                png = await Task.Run(() => RenderSvgPng(_smartSvgBytes));
            }
            await File.WriteAllBytesAsync(path, png);
            StatusMessage = $"Đã lưu PNG nền trong suốt: {Path.GetFileName(path)}";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or FormatException or InvalidDataException)
        {
            StatusMessage = $"Không thể lưu PNG: {error.Message}";
        }
    }

    private static byte[] RenderSvgPng(byte[] svgBytes)
    {
        using var svg = new SKSvg();
        svg.FromSvg(System.Text.Encoding.UTF8.GetString(svgBytes));
        var picture = svg.Picture ?? throw new InvalidDataException("Không đọc được SVG.");
        var bounds = picture.CullRect;
        var width = Math.Max(1, (int)Math.Ceiling(bounds.Width));
        var height = Math.Max(1, (int)Math.Ceiling(bounds.Height));
        using var bitmap = new SKBitmap(new SKImageInfo(width, height, SKColorType.Rgba8888, SKAlphaType.Premul));
        using (var canvas = new SKCanvas(bitmap))
        {
            canvas.Clear(SKColors.Transparent);
            canvas.DrawPicture(picture);
        }
        using var image = SKImage.FromBitmap(bitmap);
        using var data = image.Encode(SKEncodedImageFormat.Png, 100);
        return data.ToArray();
    }

    private async Task SaveBothAsync()
    {
        if (!_smartHasResult || !_contourHasResult) return;
        var smartSaved = await SaveEngineResultAsync("smart_reconstruction");
        if (!smartSaved)
        {
            if (_smartSvgBytes is not null) StatusMessage = "Lưu cặp SVG đã dừng trước khi lưu Smart Reconstruction.";
            return;
        }
        var contourSaved = await SaveEngineResultAsync("contour_preserving");
        if (!contourSaved)
            StatusMessage = "Đã lưu Smart Reconstruction; lưu Contour-Preserving đã bị hủy hoặc thất bại.";
        else
            StatusMessage = "Đã lưu cả hai SVG nguyên bản từ backend.";
    }

    private void SetZoom(object? parameter)
    {
        switch (parameter?.ToString()?.ToLowerInvariant())
        {
            case "in": ZoomFactor *= 1.2; break;
            case "out": ZoomFactor /= 1.2; break;
            case "100":
            case "fit":
                ZoomFactor = 1;
                PanX = PanY = 0;
                break;
        }
    }

    private void NotifyCommands()
    {
        if (RunCommand is AsyncRelayCommand run) run.NotifyCanExecuteChanged();
        CompareCommand?.NotifyCanExecuteChanged();
        SaveResultCommand?.NotifyCanExecuteChanged();
        SavePngCommand?.NotifyCanExecuteChanged();
        SaveSmartResultCommand?.NotifyCanExecuteChanged();
        SaveContourResultCommand?.NotifyCanExecuteChanged();
        SaveBothCommand?.NotifyCanExecuteChanged();
    }

    private void SetPreview(ref BitmapImage? field, BitmapImage? value, string propertyName)
    {
        if (SetProperty(ref field, value, propertyName))
        {
            OnPropertyChanged(nameof(SelectedResultPreviewImage));
            OnPropertyChanged(nameof(ShowSingleResultPreview));
            OnPropertyChanged(nameof(ShowSingleResultPlaceholder));
            OnPropertyChanged(nameof(SmartHasNoPreview));
            OnPropertyChanged(nameof(ContourHasNoPreview));
            OnPropertyChanged(nameof(SmartHasPreview));
            OnPropertyChanged(nameof(ContourHasPreview));
        }
    }

    private string EngineName(string method) => IsCutoutMode ? "Tách nền" : "Vector màu theo lớp";

    private static string FormatError(Exception error) => error switch
    {
        BackendApiException { Code: "CONTOUR_EXPERIMENTAL_DISABLED" } => "Contour đang tắt ở backend. Bật cờ experimental rồi khởi động lại MediaStudio.",
        BackendApiException { Code: "CONTOUR_DEPENDENCY_MISSING" } => "Thiếu scikit-image 0.26.0. Hãy cài dependency Contour và khởi động lại backend.",
        BackendApiException { StatusCode: System.Net.HttpStatusCode.Unauthorized } => "Phiên xác thực backend không hợp lệ. Hãy khởi động lại MediaStudio.",
        BackendApiException { StatusCode: System.Net.HttpStatusCode.UnprocessableEntity } => "Thiết lập gửi lên không hợp lệ. Hãy kiểm tra chất lượng và kiểu chữ.",
        BackendApiException { StatusCode: System.Net.HttpStatusCode.ServiceUnavailable } => "Backend hoặc engine thử nghiệm hiện chưa sẵn sàng.",
        BackendApiException apiError => apiError.Message,
        BackendJobException { ErrorCode: "CONTOUR_DEPENDENCY_MISSING" } => "Thiếu scikit-image 0.26.0. Hãy cài dependency Contour và khởi động lại backend.",
        BackendJobException { ErrorCode: "CONTOUR_RESOURCE_MEMORY_LIMIT" } => "Ảnh vượt giới hạn bộ nhớ của engine Contour. Smart Reconstruction vẫn có thể chạy.",
        BackendJobException { ErrorCode: "CONTOUR_EXPERIMENTAL_DISABLED" } => "Contour đang tắt ở backend. Bật cờ experimental rồi khởi động lại MediaStudio.",
        BackendJobException jobError => jobError.Message,
        HttpRequestException => "Không kết nối được backend local. Kiểm tra backend.log hoặc khởi động lại MediaStudio.",
        TimeoutException => error.Message,
        InvalidDataException => error.Message,
        _ => error.Message
    };

    private static BitmapImage RenderSvgPreview(byte[] svgBytes)
    {
        using var svg = new SKSvg();
        svg.FromSvg(System.Text.Encoding.UTF8.GetString(svgBytes));
        var picture = svg.Picture ?? throw new InvalidDataException("Svg.Skia không thể đọc SVG để xem trước.");
        var bounds = picture.CullRect;
        var sourceWidth = Math.Max(1, bounds.Width);
        var sourceHeight = Math.Max(1, bounds.Height);
        const int maxPreviewDimension = 1024;
        var scale = Math.Min(maxPreviewDimension / sourceWidth, maxPreviewDimension / sourceHeight);
        var width = Math.Clamp((int)Math.Ceiling(sourceWidth * scale), 1, maxPreviewDimension);
        var height = Math.Clamp((int)Math.Ceiling(sourceHeight * scale), 1, maxPreviewDimension);
        using var bitmap = new SKBitmap(new SKImageInfo(width, height, SKColorType.Rgba8888, SKAlphaType.Premul));
        using (var canvas = new SKCanvas(bitmap))
        {
            canvas.Clear(SKColors.Transparent);
            canvas.Scale(scale);
            canvas.Translate(-bounds.Left, -bounds.Top);
            canvas.DrawPicture(picture);
            canvas.Flush();
        }

        using var image = SKImage.FromBitmap(bitmap);
        using var encoded = image.Encode(SKEncodedImageFormat.Png, 100)
            ?? throw new InvalidDataException("Svg.Skia không tạo được bitmap preview.");
        using var stream = new MemoryStream(encoded.ToArray());
        var preview = new BitmapImage();
        preview.BeginInit();
        preview.CacheOption = BitmapCacheOption.OnLoad;
        preview.StreamSource = stream;
        preview.EndInit();
        preview.Freeze();
        return preview;
    }

    private static Brush CreateCheckerboardBrush()
    {
        var drawing = new DrawingGroup();
        drawing.Children.Add(new GeometryDrawing(Brushes.White, null, new RectangleGeometry(new Rect(0, 0, 20, 20))));
        var gray = new SolidColorBrush(Color.FromRgb(229, 231, 235));
        gray.Freeze();
        drawing.Children.Add(new GeometryDrawing(gray, null, new RectangleGeometry(new Rect(0, 0, 10, 10))));
        drawing.Children.Add(new GeometryDrawing(gray, null, new RectangleGeometry(new Rect(10, 10, 10, 10))));
        drawing.Freeze();
        var brush = new DrawingBrush(drawing)
        {
            TileMode = TileMode.Tile,
            Viewport = new Rect(0, 0, 20, 20),
            ViewportUnits = BrushMappingMode.Absolute,
            Viewbox = new Rect(0, 0, 20, 20),
            ViewboxUnits = BrushMappingMode.Absolute,
            Stretch = Stretch.Fill
        };
        brush.Freeze();
        return brush;
    }
}
