using System.ComponentModel;
using System.IO;
using System.Net.Http;
using System.Runtime.CompilerServices;
using System.Text;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using MediaStudio.Desktop.Infrastructure;
using MediaStudio.Desktop.Services;
using SkiaSharp;
using Svg.Skia;

namespace MediaStudio.Desktop.ViewModels;

public enum ImageToolKind
{
    Upscale,
    Vectorize,
    DieCutLine
}

public sealed class ImageToolsViewModel : ObservableObject
{
    private ImageToolKind _selectedTool = ImageToolKind.Upscale;
    private ObservableObject _activePage;

    public ImageToolsViewModel(IImagePicker imagePicker, MediaStudioApiClient? apiClient, BackendHealth? backendHealth = null)
    {
        Upscale = new UpscaleToolViewModel(imagePicker, apiClient);
        Vectorize = new VectorizeToolViewModel(imagePicker, apiClient, backendHealth);
        DieCutLine = new DieCutLineToolViewModel(imagePicker, apiClient);
        _activePage = Upscale;
        SelectToolCommand = new RelayCommand(SelectTool);
    }

    public UpscaleToolViewModel Upscale { get; }
    public VectorizeToolViewModel Vectorize { get; }
    public DieCutLineToolViewModel DieCutLine { get; }

    public ImageToolKind SelectedTool
    {
        get => _selectedTool;
        private set => SetProperty(ref _selectedTool, value);
    }

    public ObservableObject ActivePage
    {
        get => _activePage;
        private set => SetProperty(ref _activePage, value);
    }

    public RelayCommand SelectToolCommand { get; }

    private void SelectTool(object? parameter)
    {
        if (parameter is not ImageToolKind kind)
        {
            return;
        }

        SelectedTool = kind;
        ActivePage = kind switch
        {
            ImageToolKind.Vectorize => Vectorize,
            ImageToolKind.DieCutLine => DieCutLine,
            _ => Upscale
        };
    }
}

public abstract class ImageToolPageViewModel : ObservableObject
{
    private readonly IImagePicker _imagePicker;
    private string _inputFileName;
    private string _inputDimensions;
    private string _pixelDimensions;
    private string _statusMessage;
    private BitmapImage? _previewImage;
    private bool _hasImportedImage;
    private string? _selectedImagePath;

    protected ImageToolPageViewModel(IImagePicker imagePicker, string inputFileName, string inputDimensions)
    {
        _imagePicker = imagePicker;
        _inputFileName = inputFileName;
        _inputDimensions = inputDimensions;
        _pixelDimensions = inputDimensions.Split("  ·", StringSplitOptions.None)[0];
        _statusMessage = "Chọn ảnh để bắt đầu xử lý.";
        OpenImageCommand = new RelayCommand(_ => OpenImage(), _ => CanOpenImage);
        RunCommand = new RelayCommand(_ =>
            StatusMessage = "Giao diện đã sẵn sàng. Tác vụ sẽ chạy khi Python backend được tích hợp.");
    }

    public string InputFileName
    {
        get => _inputFileName;
        private set => SetProperty(ref _inputFileName, value);
    }

    public string InputDimensions
    {
        get => _inputDimensions;
        private set => SetProperty(ref _inputDimensions, value);
    }

    public string PixelDimensions
    {
        get => _pixelDimensions;
        private set => SetProperty(ref _pixelDimensions, value);
    }

    public string StatusMessage
    {
        get => _statusMessage;
        protected set => SetProperty(ref _statusMessage, value);
    }

    public BitmapImage? PreviewImage
    {
        get => _previewImage;
        private set => SetProperty(ref _previewImage, value);
    }

    public bool HasImportedImage
    {
        get => _hasImportedImage;
        private set
        {
            if (SetProperty(ref _hasImportedImage, value))
            {
                OnPropertyChanged(nameof(ShowSampleArt));
                OnImageAvailabilityChanged();
            }
        }
    }

    public bool ShowSampleArt => !HasImportedImage;
    protected string? SelectedImagePath { get => _selectedImagePath; private set => _selectedImagePath = value; }

    public RelayCommand OpenImageCommand { get; }
    public ICommand RunCommand { get; protected set; }
    protected virtual bool CanOpenImage => true;

    private void OpenImage()
    {
        var path = _imagePicker.PickImage();
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        try
        {
            var image = new BitmapImage();
            image.BeginInit();
            image.CacheOption = BitmapCacheOption.OnLoad;
            image.UriSource = new Uri(path, UriKind.Absolute);
            image.EndInit();
            image.Freeze();

            var info = new FileInfo(path);
            SelectedImagePath = path;
            PreviewImage = image;
            HasImportedImage = true;
            InputFileName = info.Name;
            InputDimensions = $"{image.PixelWidth} × {image.PixelHeight} px  ·  {FormatSize(info.Length)}";
            PixelDimensions = $"{image.PixelWidth} × {image.PixelHeight} px";
            StatusMessage = "Đã nạp ảnh vào bản xem trước · Chưa gửi tệp đi đâu";
            OnImageChanged(image.PixelWidth, image.PixelHeight);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or UriFormatException or NotSupportedException or FormatException or OutOfMemoryException)
        {
            StatusMessage = "Không thể mở ảnh này. Hãy chọn PNG, JPEG, BMP hoặc TIFF.";
        }
    }

    protected virtual void OnImageChanged(int width, int height)
    {
    }

    protected virtual void OnImageAvailabilityChanged()
    {
    }

    protected static string FormatSize(long bytes) => bytes switch
    {
        < 1024 => $"{bytes} B",
        < 1024 * 1024 => $"{bytes / 1024d:0.#} KB",
        _ => $"{bytes / (1024d * 1024d):0.#} MB"
    };
}

public sealed class UpscaleToolViewModel : ImageToolPageViewModel
{
    private readonly IImagePicker _imagePicker;
    private readonly MediaStudioApiClient? _apiClient;
    private int _scaleFactor = 4;
    private bool _reduceNoise = true;
    private bool _sharpen = true;
    private string _model = "Real-ESRGAN";
    private string _outputFormat = "PNG";
    private bool _isProcessing;
    private bool _hasResult;
    private int _progress;
    private bool _progressIsIndeterminate;
    private string _runButtonLabel = "Bắt đầu nâng cấp";
    private BitmapImage? _resultPreviewImage;
    private byte[]? _resultBytes;

    public UpscaleToolViewModel(IImagePicker imagePicker, MediaStudioApiClient? apiClient)
        : base(imagePicker, "dolomites-lake.jpg", "1920 × 1080 px  ·  2,4 MB")
    {
        _imagePicker = imagePicker;
        _apiClient = apiClient;
        RunCommand = new AsyncRelayCommand(RunUpscaleAsync, _ => _apiClient is not null && HasImportedImage && !IsProcessing);
        SaveResultCommand = new AsyncRelayCommand(SaveResultAsync, _ => HasResult && !IsProcessing);
        SetScaleCommand = new RelayCommand(parameter =>
        {
            if (parameter is int scale)
            {
                ScaleFactor = scale;
            }
            else if (int.TryParse(parameter?.ToString(), out scale))
            {
                ScaleFactor = scale;
            }
        });
    }

    public int ScaleFactor
    {
        get => _scaleFactor;
        set
        {
            if (SetProperty(ref _scaleFactor, value))
            {
                OnPropertyChanged(nameof(OutputDimensions));
                OnPropertyChanged(nameof(ScaleDescription));
                ClearResult();
            }
        }
    }

    public bool ReduceNoise { get => _reduceNoise; set { if (!IsProcessing && SetProperty(ref _reduceNoise, value)) ClearResult(); } }
    public bool Sharpen { get => _sharpen; set { if (!IsProcessing && SetProperty(ref _sharpen, value)) ClearResult(); } }
    public string Model { get => _model; set { if (!IsProcessing && SetProperty(ref _model, value)) ClearResult(); } }
    public string OutputFormat { get => _outputFormat; set { if (!IsProcessing && SetProperty(ref _outputFormat, value)) ClearResult(); } }
    public string OutputDimensions => $"{SourceWidth * (long)ScaleFactor:N0} × {SourceHeight * (long)ScaleFactor:N0} px";
    public string ScaleDescription => ScaleFactor == 8
        ? "8× = 4× AI + resize thêm 2×"
        : Model == "Real-ESRGAN Anime" && ScaleFactor == 2
            ? "Anime 4× AI + thu nhỏ Lanczos còn 2×"
            : $"Mô hình AI nâng cấp trực tiếp {ScaleFactor}×";
    public string RunButtonLabel { get => _runButtonLabel; private set => SetProperty(ref _runButtonLabel, value); }
    public bool IsProcessing
    {
        get => _isProcessing;
        private set
        {
            if (SetProperty(ref _isProcessing, value))
            {
                ((AsyncRelayCommand)RunCommand).NotifyCanExecuteChanged();
                SaveResultCommand.NotifyCanExecuteChanged();
            }
        }
    }
    public bool HasResult
    {
        get => _hasResult;
        private set
        {
            if (SetProperty(ref _hasResult, value))
            {
                OnPropertyChanged(nameof(ShowSaveButton));
                SaveResultCommand.NotifyCanExecuteChanged();
            }
        }
    }
    public bool ShowSaveButton => HasResult;
    public int Progress { get => _progress; private set => SetProperty(ref _progress, value); }
    public bool ProgressIsIndeterminate { get => _progressIsIndeterminate; private set => SetProperty(ref _progressIsIndeterminate, value); }
    public BitmapImage? ResultPreviewImage { get => _resultPreviewImage; private set => SetProperty(ref _resultPreviewImage, value); }
    public AsyncRelayCommand SaveResultCommand { get; }
    public RelayCommand SetScaleCommand { get; }

    protected override void OnImageChanged(int width, int height)
    {
        SourceWidth = width;
        SourceHeight = height;
        ResultPreviewImage = null;
        _resultBytes = null;
        HasResult = false;
        Progress = 0;
        StatusMessage = _apiClient is null ? "Backend chưa sẵn sàng. Kiểm tra phần cài đặt backend." : "Ảnh đã sẵn sàng để nâng cấp.";
        OnPropertyChanged(nameof(OutputDimensions));
    }

    protected override void OnImageAvailabilityChanged() => ((AsyncRelayCommand)RunCommand).NotifyCanExecuteChanged();
    protected override bool CanOpenImage => !IsProcessing;

    private int SourceWidth { get; set; } = 1920;
    private int SourceHeight { get; set; } = 1080;

    private async Task RunUpscaleAsync()
    {
        if (_apiClient is null || string.IsNullOrWhiteSpace(SelectedImagePath))
        {
            StatusMessage = "Backend chưa sẵn sàng hoặc chưa chọn ảnh.";
            return;
        }

        IsProcessing = true;
        HasResult = false;
        ResultPreviewImage = null;
        _resultBytes = null;
        Progress = 0;
        ProgressIsIndeterminate = true;
        RunButtonLabel = "Đang nâng cấp ảnh…";
        StatusMessage = "Đang gửi ảnh tới Python backend.";
        try
        {
            var asset = await _apiClient.ImportImageAsync(SelectedImagePath);
            StatusMessage = "Đang xếp tác vụ nâng cấp ảnh.";
            var job = await _apiClient.StartUpscaleAsync(new UpscaleRequest
            {
                AssetId = asset.AssetId,
                Scale = ScaleFactor,
                Model = Model,
                ReduceNoise = ReduceNoise,
                Sharpen = Sharpen,
                OutputFormat = OutputFormat
            });

            while (job.State is not ("succeeded" or "failed"))
            {
                await Task.Delay(400);
                job = await _apiClient.GetJobAsync(job.JobId);
                Progress = Math.Clamp(job.Progress, 0, 100);
                ProgressIsIndeterminate = job.IsIndeterminate;
                StatusMessage = job.Stage;
            }

            ProgressIsIndeterminate = false;
            if (job.State != "succeeded")
            {
                Progress = 0;
                StatusMessage = job.Error ?? "Không thể nâng cấp ảnh.";
                return;
            }

            _resultBytes = await _apiClient.DownloadResultAsync(job.JobId);
            ResultPreviewImage = LoadBitmap(_resultBytes);
            HasResult = true;
            Progress = 100;
            StatusMessage = $"Hoàn tất · {job.ResultWidth:N0} × {job.ResultHeight:N0} px · {FormatSize(job.ResultSize ?? _resultBytes.LongLength)}";
        }
        catch (Exception error)
        {
            ProgressIsIndeterminate = false;
            Progress = 0;
            StatusMessage = error.Message;
        }
        finally
        {
            IsProcessing = false;
            RunButtonLabel = "Bắt đầu nâng cấp";
        }
    }

    private void ClearResult()
    {
        if (IsProcessing) return;
        var hadResult = HasResult;
        ResultPreviewImage = null;
        _resultBytes = null;
        HasResult = false;
        Progress = 0;
        OnPropertyChanged(nameof(ScaleDescription));
        if (hadResult) StatusMessage = "Thiết lập đã đổi · hãy chạy lại để tạo kết quả mới.";
    }

    private async Task SaveResultAsync()
    {
        if (_resultBytes is null)
        {
            StatusMessage = "Chưa có ảnh kết quả để lưu.";
            return;
        }

        var extension = OutputFormat.ToUpperInvariant() switch
        {
            "JPG" => ".jpg",
            "TIFF" => ".tif",
            _ => ".png"
        };
        var defaultName = $"{Path.GetFileNameWithoutExtension(InputFileName)}_upscaled_{ScaleFactor}x{extension}";
        var path = _imagePicker.PickSavePath(defaultName, OutputFormat);
        if (string.IsNullOrWhiteSpace(path)) return;
        if (!(OutputFormat.Equals("JPG", StringComparison.OrdinalIgnoreCase)
                ? path.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase) || path.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase)
                : path.EndsWith(extension, StringComparison.OrdinalIgnoreCase)))
        {
            path = Path.ChangeExtension(path, extension);
        }

        try
        {
            await File.WriteAllBytesAsync(path, _resultBytes);
            StatusMessage = $"Đã lưu ảnh: {Path.GetFileName(path)}";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            StatusMessage = $"Không thể lưu ảnh: {error.Message}";
        }
    }

    private static BitmapImage LoadBitmap(byte[] bytes)
    {
        using var stream = new MemoryStream(bytes);
        var image = new BitmapImage();
        image.BeginInit();
        image.CacheOption = BitmapCacheOption.OnLoad;
        image.StreamSource = stream;
        image.EndInit();
        image.Freeze();
        return image;
    }
}

public sealed class DieCutLineToolViewModel : ImageToolPageViewModel
{
    private readonly IImagePicker _imagePicker;
    private readonly MediaStudioApiClient? _apiClient;
    private readonly List<DieCutStrokeRequest> _maskStrokes = [];
    private double _offsetMillimeters = 2;
    private double _artworkWidthMillimeters = 100;
    private bool _autoDetect = true;
    private bool _smoothPath = true;
    private string _complexity = "Vừa";
    private string _maskBrush = "foreground";
    private bool _isMaskEditing;
    private bool _isProcessing;
    private bool _hasResult;
    private string _runButtonLabel = "Tạo đường bế";
    private BitmapImage? _cutLinePreviewImage;
    private byte[]? _resultBytes;
    private int _sourceWidth = 1200;
    private int _sourceHeight = 1200;
    private int _resultPathCount;
    private int _maskStrokeRevision;

    public DieCutLineToolViewModel(IImagePicker imagePicker, MediaStudioApiClient? apiClient)
        : base(imagePicker, "sticker-hoa-cuc.png", "1200 × 1200 px  ·  486 KB  ·  Nền trong suốt")
    {
        _imagePicker = imagePicker;
        _apiClient = apiClient;
        AdjustOffsetCommand = new RelayCommand(parameter =>
        {
            if (!IsProcessing && double.TryParse(parameter?.ToString(), System.Globalization.CultureInfo.InvariantCulture, out var adjustment))
            {
                OffsetMillimeters = Math.Clamp(OffsetMillimeters + adjustment, 0, 20);
            }
        });
        SelectComplexityCommand = new RelayCommand(parameter =>
        {
            if (!IsProcessing && parameter is string complexity && complexity is "Đơn giản" or "Vừa" or "Chi tiết")
            {
                Complexity = complexity;
            }
        });
        SelectMaskBrushCommand = new RelayCommand(parameter =>
        {
            if (!IsProcessing && parameter is string brush && brush is "foreground" or "background")
            {
                MaskBrush = brush;
            }
        });
        ClearMaskStrokesCommand = new RelayCommand(_ => ClearMaskStrokes(), _ => !IsProcessing && _maskStrokes.Count > 0);
        RunCommand = new AsyncRelayCommand(RunDieCutAsync, _ => _apiClient is not null && HasImportedImage && !IsProcessing);
        SaveResultCommand = new AsyncRelayCommand(SaveResultAsync, _ => HasResult && !IsProcessing);
    }

    public double OffsetMillimeters
    {
        get => _offsetMillimeters;
        set { if (!IsProcessing && SetProperty(ref _offsetMillimeters, Math.Clamp(value, 0, 20))) ClearResult(); }
    }
    public double ArtworkWidthMillimeters
    {
        get => _artworkWidthMillimeters;
        set
        {
            if (IsProcessing) return;
            var bounded = Math.Clamp(double.IsFinite(value) ? value : 100, 1, 2000);
            if (SetProperty(ref _artworkWidthMillimeters, bounded))
            {
                OnPropertyChanged(nameof(ArtworkHeightMillimeters));
                ClearResult();
            }
        }
    }
    public double ArtworkHeightMillimeters => _sourceWidth > 0 ? ArtworkWidthMillimeters * _sourceHeight / _sourceWidth : ArtworkWidthMillimeters;
    public string PhysicalSizeSummary => $"{ArtworkWidthMillimeters:0.#} × {ArtworkHeightMillimeters:0.#} mm";
    public bool AutoDetect { get => _autoDetect; set { if (!IsProcessing && SetProperty(ref _autoDetect, value)) ClearResult(); } }
    public bool SmoothPath { get => _smoothPath; set { if (!IsProcessing && SetProperty(ref _smoothPath, value)) ClearResult(); } }
    public string Complexity { get => _complexity; set { if (!IsProcessing && SetProperty(ref _complexity, value)) ClearResult(); } }
    public string MaskBrush
    {
        get => _maskBrush;
        private set
        {
            if (SetProperty(ref _maskBrush, value))
            {
                OnPropertyChanged(nameof(MaskBrushLabel));
                OnPropertyChanged(nameof(MaskBrushColor));
            }
        }
    }
    public string MaskBrushLabel => MaskBrush == "foreground" ? "Giữ chủ thể" : "Xóa nền";
    public string MaskBrushColor => MaskBrush == "foreground" ? "#23865B" : "#D94C5C";
    public bool IsMaskEditing { get => _isMaskEditing; set => SetProperty(ref _isMaskEditing, value); }
    public int SourceWidth => _sourceWidth;
    public int SourceHeight => _sourceHeight;
    public int MaskStrokeRevision { get => _maskStrokeRevision; private set => SetProperty(ref _maskStrokeRevision, value); }
    public int ResultPathCount { get => _resultPathCount; private set { if (SetProperty(ref _resultPathCount, value)) OnPropertyChanged(nameof(OutputSummary)); } }
    public string OutputSummary => HasResult ? $"{ResultPathCount} đường khép kín" : "Đường bế SVG";
    public bool ShowCutLinePreview => HasResult && CutLinePreviewImage is not null;
    public bool ShowCutLinePlaceholder => HasImportedImage && !HasResult;
    public bool ShowSaveButton => HasResult;
    public bool IsProcessing
    {
        get => _isProcessing;
        private set
        {
            if (SetProperty(ref _isProcessing, value))
            {
                ((AsyncRelayCommand)RunCommand).NotifyCanExecuteChanged();
                SaveResultCommand.NotifyCanExecuteChanged();
                OpenImageCommand.NotifyCanExecuteChanged();
                ClearMaskStrokesCommand.NotifyCanExecuteChanged();
                OnPropertyChanged(nameof(CanEditSettings));
            }
        }
    }
    public bool CanEditSettings => !IsProcessing;
    public bool HasResult
    {
        get => _hasResult;
        private set
        {
            if (SetProperty(ref _hasResult, value))
            {
                OnPropertyChanged(nameof(ShowCutLinePreview));
                OnPropertyChanged(nameof(ShowCutLinePlaceholder));
                OnPropertyChanged(nameof(ShowSaveButton));
                OnPropertyChanged(nameof(OutputSummary));
                SaveResultCommand.NotifyCanExecuteChanged();
            }
        }
    }
    public string RunButtonLabel { get => _runButtonLabel; private set => SetProperty(ref _runButtonLabel, value); }
    public BitmapImage? CutLinePreviewImage
    {
        get => _cutLinePreviewImage;
        private set
        {
            if (SetProperty(ref _cutLinePreviewImage, value)) OnPropertyChanged(nameof(ShowCutLinePreview));
        }
    }
    public RelayCommand AdjustOffsetCommand { get; }
    public RelayCommand SelectComplexityCommand { get; }
    public RelayCommand SelectMaskBrushCommand { get; }
    public RelayCommand ClearMaskStrokesCommand { get; }
    public AsyncRelayCommand SaveResultCommand { get; }

    protected override bool CanOpenImage => !IsProcessing;
    protected override void OnImageAvailabilityChanged() => ((AsyncRelayCommand)RunCommand).NotifyCanExecuteChanged();

    protected override void OnImageChanged(int width, int height)
    {
        _sourceWidth = width;
        _sourceHeight = height;
        OnPropertyChanged(nameof(SourceWidth));
        OnPropertyChanged(nameof(SourceHeight));
        OnPropertyChanged(nameof(ArtworkHeightMillimeters));
        OnPropertyChanged(nameof(PhysicalSizeSummary));
        IsMaskEditing = false;
        ClearMaskStrokes();
        ClearResult();
        StatusMessage = _apiClient is null
            ? "Python backend chưa sẵn sàng. Hãy kiểm tra trạng thái kết nối."
            : "Ảnh đã nạp. Kiểm tra mask, kích thước in và khoảng bù trước khi tạo đường bế.";
    }

    public void AddMaskStroke(bool foreground, IReadOnlyList<DieCutPointRequest> points)
    {
        if (!IsMaskEditing || IsProcessing || points.Count == 0) return;
        _maskStrokes.Add(new DieCutStrokeRequest
        {
            Mode = foreground ? "foreground" : "background",
            Points = points.ToList()
        });
        ClearResult();
        ClearMaskStrokesCommand.NotifyCanExecuteChanged();
        StatusMessage = $"Đã thêm nét {(foreground ? "Giữ" : "Bỏ")} · các nét sẽ được dùng để tinh chỉnh mask.";
    }

    public void ClearMaskStrokes()
    {
        if (IsProcessing) return;
        _maskStrokes.Clear();
        MaskStrokeRevision++;
        ClearResult();
        ClearMaskStrokesCommand.NotifyCanExecuteChanged();
        if (HasImportedImage) StatusMessage = "Đã xóa các nét hiệu chỉnh mask.";
    }

    private void ClearResult()
    {
        if (IsProcessing) return;
        var hadResult = HasResult;
        CutLinePreviewImage = null;
        _resultBytes = null;
        ResultPathCount = 0;
        HasResult = false;
        if (hadResult) StatusMessage = "Thiết lập đã đổi · hãy tạo lại đường bế.";
    }

    private async Task RunDieCutAsync()
    {
        if (_apiClient is null || string.IsNullOrWhiteSpace(SelectedImagePath))
        {
            StatusMessage = "Backend chưa sẵn sàng hoặc bạn chưa chọn ảnh.";
            return;
        }
        if (ArtworkWidthMillimeters < 1)
        {
            StatusMessage = "Nhập chiều rộng in thực tế (từ 1 mm trở lên) để quy đổi khoảng bù.";
            return;
        }

        IsProcessing = true;
        HasResult = false;
        CutLinePreviewImage = null;
        _resultBytes = null;
        ResultPathCount = 0;
        IsMaskEditing = false;
        StatusMessage = "Đang gửi ảnh tới Python backend.";
        RunButtonLabel = "Đang tạo đường bế…";
        try
        {
            var asset = await _apiClient.ImportImageAsync(SelectedImagePath);
            var job = await _apiClient.StartDieCutAsync(new DieCutRequest
            {
                AssetId = asset.AssetId,
                OffsetMillimeters = OffsetMillimeters,
                ArtworkWidthMillimeters = ArtworkWidthMillimeters,
                AutoDetect = AutoDetect,
                SmoothPath = SmoothPath,
                Complexity = Complexity,
                Strokes = _maskStrokes.ToList()
            });
            while (job.State is not ("succeeded" or "failed"))
            {
                await Task.Delay(350);
                job = await _apiClient.GetJobAsync(job.JobId);
                StatusMessage = job.Stage;
            }
            if (job.State != "succeeded")
            {
                StatusMessage = job.Error ?? "Không thể tạo đường bế.";
                return;
            }

            _resultBytes = await _apiClient.DownloadResultAsync(job.JobId);
            CutLinePreviewImage = RenderSvgPreview(_resultBytes);
            ResultPathCount = job.ResultPaths ?? 0;
            HasResult = true;
            StatusMessage = $"Hoàn tất · {ResultPathCount} đường bế · {FormatSize(job.ResultSize ?? _resultBytes.LongLength)}";
        }
        catch (Exception error)
        {
            StatusMessage = error.Message;
        }
        finally
        {
            IsProcessing = false;
            RunButtonLabel = "Tạo đường bế";
        }
    }

    private async Task SaveResultAsync()
    {
        if (_resultBytes is null)
        {
            StatusMessage = "Chưa có đường bế để lưu.";
            return;
        }
        var path = _imagePicker.PickSavePath($"{Path.GetFileNameWithoutExtension(InputFileName)}_die-cut.svg", "SVG");
        if (string.IsNullOrWhiteSpace(path)) return;
        if (!path.EndsWith(".svg", StringComparison.OrdinalIgnoreCase)) path = Path.ChangeExtension(path, ".svg");
        try
        {
            await File.WriteAllBytesAsync(path, _resultBytes);
            StatusMessage = $"Đã lưu SVG: {Path.GetFileName(path)}";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            StatusMessage = $"Không thể lưu SVG: {error.Message}";
        }
    }

    private static BitmapImage RenderSvgPreview(byte[] svgBytes)
    {
        using var svg = new SKSvg();
        svg.FromSvg(Encoding.UTF8.GetString(svgBytes));
        var picture = svg.Picture ?? throw new InvalidDataException("SVG đường bế không thể hiển thị.");
        var bounds = picture.CullRect;
        var sourceWidth = Math.Max(1, bounds.Width);
        var sourceHeight = Math.Max(1, bounds.Height);
        var scale = Math.Min(1200f / sourceWidth, 1200f / sourceHeight);
        var width = Math.Clamp((int)Math.Ceiling(sourceWidth * scale), 1, 1200);
        var height = Math.Clamp((int)Math.Ceiling(sourceHeight * scale), 1, 1200);
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
            ?? throw new InvalidDataException("Không tạo được bản xem trước đường bế.");
        using var stream = new MemoryStream(encoded.ToArray());
        var preview = new BitmapImage();
        preview.BeginInit();
        preview.CacheOption = BitmapCacheOption.OnLoad;
        preview.StreamSource = stream;
        preview.EndInit();
        preview.Freeze();
        return preview;
    }
}

public abstract class ObservableObject : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected bool SetProperty<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
        {
            return false;
        }

        field = value;
        OnPropertyChanged(propertyName);
        return true;
    }

    protected void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
