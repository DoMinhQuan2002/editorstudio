using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace MediaStudio.Desktop.Views;

/// <summary>A viewport-sized image presenter with normalized pan values for synchronized compare panes.</summary>
public sealed class ZoomPanImage : UserControl
{
    private readonly Border _frame;
    private readonly Image _image;
    private readonly ScaleTransform _scale = new(1, 1);
    private readonly TranslateTransform _translate = new();
    private Point _lastPointer;
    private bool _isDragging;

    public static readonly DependencyProperty SourceProperty = DependencyProperty.Register(
        nameof(Source), typeof(ImageSource), typeof(ZoomPanImage),
        new FrameworkPropertyMetadata(null, FrameworkPropertyMetadataOptions.AffectsRender, OnViewStateChanged));

    public static readonly DependencyProperty ZoomProperty = DependencyProperty.Register(
        nameof(Zoom), typeof(double), typeof(ZoomPanImage),
        new FrameworkPropertyMetadata(1d, FrameworkPropertyMetadataOptions.BindsTwoWayByDefault, OnViewStateChanged));

    public static readonly DependencyProperty PanXProperty = DependencyProperty.Register(
        nameof(PanX), typeof(double), typeof(ZoomPanImage),
        new FrameworkPropertyMetadata(0d, FrameworkPropertyMetadataOptions.BindsTwoWayByDefault, OnViewStateChanged));

    public static readonly DependencyProperty PanYProperty = DependencyProperty.Register(
        nameof(PanY), typeof(double), typeof(ZoomPanImage),
        new FrameworkPropertyMetadata(0d, FrameworkPropertyMetadataOptions.BindsTwoWayByDefault, OnViewStateChanged));

    public static readonly DependencyProperty PreviewBackgroundProperty = DependencyProperty.Register(
        nameof(PreviewBackground), typeof(Brush), typeof(ZoomPanImage),
        new FrameworkPropertyMetadata(Brushes.White, OnViewStateChanged));

    public ZoomPanImage()
    {
        ClipToBounds = true;
        _image = new Image
        {
            Stretch = Stretch.Uniform,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            VerticalAlignment = VerticalAlignment.Stretch,
            RenderTransformOrigin = new Point(.5, .5),
            RenderTransform = new TransformGroup { Children = new TransformCollection { _scale, _translate } }
        };
        _frame = new Border
        {
            Padding = new Thickness(8),
            ClipToBounds = true,
            Child = _image
        };
        Content = _frame;
        SizeChanged += (_, _) => UpdateTransform();
        Loaded += (_, _) => UpdateTransform();
        MouseWheel += OnMouseWheel;
        MouseLeftButtonDown += OnMouseDown;
        MouseLeftButtonUp += OnMouseUp;
        MouseMove += OnMouseMove;
        LostMouseCapture += (_, _) => EndDrag();
    }

    public ImageSource? Source { get => (ImageSource?)GetValue(SourceProperty); set => SetValue(SourceProperty, value); }
    public double Zoom { get => (double)GetValue(ZoomProperty); set => SetValue(ZoomProperty, value); }
    public double PanX { get => (double)GetValue(PanXProperty); set => SetValue(PanXProperty, value); }
    public double PanY { get => (double)GetValue(PanYProperty); set => SetValue(PanYProperty, value); }
    public Brush PreviewBackground { get => (Brush)GetValue(PreviewBackgroundProperty); set => SetValue(PreviewBackgroundProperty, value); }

    private static void OnViewStateChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs e)
    {
        var view = (ZoomPanImage)dependencyObject;
        if (e.Property == SourceProperty) view._image.Source = (ImageSource?)e.NewValue;
        if (e.Property == PreviewBackgroundProperty) view._frame.Background = (Brush)e.NewValue;
        view.UpdateTransform();
    }

    private void OnMouseWheel(object sender, MouseWheelEventArgs e)
    {
        var factor = e.Delta > 0 ? 1.15 : 1 / 1.15;
        SetCurrentValue(ZoomProperty, Math.Clamp(Zoom * factor, .1, 8));
        e.Handled = true;
    }

    private void OnMouseDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton != MouseButton.Left) return;
        _isDragging = true;
        _lastPointer = e.GetPosition(this);
        Cursor = Cursors.Hand;
        CaptureMouse();
        e.Handled = true;
    }

    private void OnMouseUp(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton != MouseButton.Left) return;
        EndDrag();
        e.Handled = true;
    }

    private void OnMouseMove(object sender, MouseEventArgs e)
    {
        if (!_isDragging || e.LeftButton != MouseButtonState.Pressed) return;
        var current = e.GetPosition(this);
        var delta = current - _lastPointer;
        _lastPointer = current;
        var (fitWidth, fitHeight) = GetFitSize();
        SetCurrentValue(PanXProperty, Math.Clamp(PanX + delta.X / Math.Max(1, fitWidth * Zoom), -1.5, 1.5));
        SetCurrentValue(PanYProperty, Math.Clamp(PanY + delta.Y / Math.Max(1, fitHeight * Zoom), -1.5, 1.5));
        e.Handled = true;
    }

    private void EndDrag()
    {
        _isDragging = false;
        Cursor = Cursors.Arrow;
        if (IsMouseCaptured) ReleaseMouseCapture();
    }

    private (double Width, double Height) GetFitSize()
    {
        var availableWidth = Math.Max(1, ActualWidth - _frame.Padding.Left - _frame.Padding.Right);
        var availableHeight = Math.Max(1, ActualHeight - _frame.Padding.Top - _frame.Padding.Bottom);
        if (_image.Source is null || _image.Source.Height <= 0) return (availableWidth, availableHeight);
        var aspect = _image.Source.Width / _image.Source.Height;
        var width = Math.Min(availableWidth, availableHeight * aspect);
        return (width, width / Math.Max(.0001, aspect));
    }

    private void UpdateTransform()
    {
        if (_image is null) return;
        _image.Source = Source;
        _frame.Background = PreviewBackground;
        var safeZoom = Math.Clamp(double.IsFinite(Zoom) ? Zoom : 1, .1, 8);
        _scale.ScaleX = safeZoom;
        _scale.ScaleY = safeZoom;
        var (fitWidth, fitHeight) = GetFitSize();
        _translate.X = PanX * fitWidth * safeZoom;
        _translate.Y = PanY * fitHeight * safeZoom;
    }
}
