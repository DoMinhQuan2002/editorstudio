using System.Windows;
using System.Windows.Media;

namespace MediaStudio.Desktop.Views;

public sealed class ProgressRing : FrameworkElement
{
    public static readonly DependencyProperty ProgressProperty = DependencyProperty.Register(
        nameof(Progress), typeof(double?), typeof(ProgressRing),
        new FrameworkPropertyMetadata(null, OnProgressChanged));

    public static readonly DependencyProperty RingBrushProperty = DependencyProperty.Register(
        nameof(RingBrush), typeof(Brush), typeof(ProgressRing),
        new FrameworkPropertyMetadata(new SolidColorBrush(Color.FromRgb(92, 75, 255)), FrameworkPropertyMetadataOptions.AffectsRender));

    public static readonly DependencyProperty TrackBrushProperty = DependencyProperty.Register(
        nameof(TrackBrush), typeof(Brush), typeof(ProgressRing),
        new FrameworkPropertyMetadata(new SolidColorBrush(Color.FromRgb(232, 229, 251)), FrameworkPropertyMetadataOptions.AffectsRender));

    public static readonly DependencyProperty ThicknessProperty = DependencyProperty.Register(
        nameof(Thickness), typeof(double), typeof(ProgressRing),
        new FrameworkPropertyMetadata(16d, FrameworkPropertyMetadataOptions.AffectsRender));

    public static readonly DependencyProperty IsActiveProperty = DependencyProperty.Register(
        nameof(IsActive), typeof(bool), typeof(ProgressRing),
        new FrameworkPropertyMetadata(true, OnAnimationSettingChanged));

    private double _rotation;
    private bool _listening;

    public ProgressRing()
    {
        Loaded += (_, _) => UpdateAnimation();
        Unloaded += (_, _) => StopAnimation();
    }

    public double? Progress { get => (double?)GetValue(ProgressProperty); set => SetValue(ProgressProperty, value); }
    public Brush RingBrush { get => (Brush)GetValue(RingBrushProperty); set => SetValue(RingBrushProperty, value); }
    public Brush TrackBrush { get => (Brush)GetValue(TrackBrushProperty); set => SetValue(TrackBrushProperty, value); }
    public double Thickness { get => (double)GetValue(ThicknessProperty); set => SetValue(ThicknessProperty, value); }
    public bool IsActive { get => (bool)GetValue(IsActiveProperty); set => SetValue(IsActiveProperty, value); }

    protected override void OnRender(DrawingContext drawingContext)
    {
        base.OnRender(drawingContext);
        var size = Math.Min(ActualWidth, ActualHeight);
        if (size <= Thickness) return;
        var center = new Point(ActualWidth / 2, ActualHeight / 2);
        var radius = size / 2 - Thickness / 2;
        var trackPen = CreatePen(TrackBrush);
        drawingContext.DrawEllipse(null, trackPen, center, radius, radius);

        var progress = Progress;
        if (progress is double value)
        {
            var sweep = Math.Clamp(value, 0, 100) * 3.6;
            if (sweep >= 359.9)
            {
                drawingContext.DrawEllipse(null, CreatePen(RingBrush), center, radius, radius);
                return;
            }
            if (sweep <= 0) return;
            DrawArc(drawingContext, center, radius, -90, sweep);
            return;
        }

        DrawArc(drawingContext, center, radius, -90 + _rotation, 78);
    }

    private void DrawArc(DrawingContext context, Point center, double radius, double startDegrees, double sweepDegrees)
    {
        var start = PointAt(center, radius, startDegrees);
        var end = PointAt(center, radius, startDegrees + sweepDegrees);
        var geometry = new StreamGeometry();
        using (var sink = geometry.Open())
        {
            sink.BeginFigure(start, false, false);
            sink.ArcTo(end, new Size(radius, radius), 0, sweepDegrees > 180,
                SweepDirection.Clockwise, true, false);
        }
        geometry.Freeze();
        context.DrawGeometry(null, CreatePen(RingBrush), geometry);
    }

    private Pen CreatePen(Brush brush)
    {
        var pen = new Pen(brush, Thickness) { StartLineCap = PenLineCap.Round, EndLineCap = PenLineCap.Round };
        if (pen.CanFreeze) pen.Freeze();
        return pen;
    }

    private static Point PointAt(Point center, double radius, double degrees)
    {
        var radians = degrees * Math.PI / 180;
        return new Point(center.X + Math.Cos(radians) * radius, center.Y + Math.Sin(radians) * radius);
    }

    private static void OnProgressChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs args)
    {
        var ring = (ProgressRing)dependencyObject;
        ring.UpdateAnimation();
        ring.InvalidateVisual();
    }

    private static void OnAnimationSettingChanged(DependencyObject dependencyObject, DependencyPropertyChangedEventArgs args) =>
        ((ProgressRing)dependencyObject).UpdateAnimation();

    private void UpdateAnimation()
    {
        if (IsLoaded && IsActive && Progress is null)
        {
            if (_listening) return;
            CompositionTarget.Rendering += OnRendering;
            _listening = true;
            return;
        }
        StopAnimation();
    }

    private void StopAnimation()
    {
        if (!_listening) return;
        CompositionTarget.Rendering -= OnRendering;
        _listening = false;
    }

    private void OnRendering(object? sender, EventArgs args)
    {
        _rotation = (_rotation + 4) % 360;
        InvalidateVisual();
    }
}
