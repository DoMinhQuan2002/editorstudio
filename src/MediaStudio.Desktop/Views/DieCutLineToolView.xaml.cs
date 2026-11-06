using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Views;

public partial class DieCutLineToolView : UserControl
{
    private bool _drawing;
    private bool _currentStrokeKeepsForeground;
    private Polyline? _currentPolyline;
    private readonly List<DieCutPointRequest> _currentPoints = [];

    public DieCutLineToolView()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (e.OldValue is INotifyPropertyChanged oldViewModel)
        {
            oldViewModel.PropertyChanged -= OnViewModelPropertyChanged;
        }
        if (e.NewValue is INotifyPropertyChanged newViewModel)
        {
            newViewModel.PropertyChanged += OnViewModelPropertyChanged;
        }
        ResetDrawing();
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(DieCutLineToolViewModel.MaskStrokeRevision))
        {
            MaskEditorCanvas.Children.Clear();
            ResetDrawing();
        }
    }

    private void MaskEditorCanvas_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (DataContext is not DieCutLineToolViewModel viewModel || !viewModel.IsMaskEditing || viewModel.IsProcessing)
        {
            return;
        }
        if (!TryMapPoint(e.GetPosition(MaskEditorCanvas), viewModel, out var normalized, out var canvasPoint))
        {
            return;
        }

        _drawing = true;
        _currentStrokeKeepsForeground = viewModel.MaskBrush == "foreground";
        _currentPoints.Clear();
        _currentPoints.Add(normalized);
        _currentPolyline = new Polyline
        {
            Stroke = new SolidColorBrush((Color)ColorConverter.ConvertFromString(viewModel.MaskBrushColor)),
            StrokeThickness = Math.Max(7, Math.Min(18, Math.Min(MaskEditorCanvas.ActualWidth, MaskEditorCanvas.ActualHeight) * 0.018)),
            StrokeStartLineCap = PenLineCap.Round,
            StrokeEndLineCap = PenLineCap.Round,
            StrokeLineJoin = PenLineJoin.Round,
            IsHitTestVisible = false
        };
        _currentPolyline.Points.Add(canvasPoint);
        MaskEditorCanvas.Children.Add(_currentPolyline);
        MaskEditorCanvas.CaptureMouse();
        e.Handled = true;
    }

    private void MaskEditorCanvas_OnMouseMove(object sender, MouseEventArgs e)
    {
        if (!_drawing || _currentPolyline is null || DataContext is not DieCutLineToolViewModel viewModel)
        {
            return;
        }
        if (!TryMapPoint(e.GetPosition(MaskEditorCanvas), viewModel, out var normalized, out var canvasPoint))
        {
            return;
        }
        var previous = _currentPolyline.Points[^1];
        if ((canvasPoint - previous).Length < 2)
        {
            return;
        }
        _currentPoints.Add(normalized);
        _currentPolyline.Points.Add(canvasPoint);
        e.Handled = true;
    }

    private void MaskEditorCanvas_OnMouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (!_drawing || DataContext is not DieCutLineToolViewModel viewModel)
        {
            return;
        }
        _drawing = false;
        MaskEditorCanvas.ReleaseMouseCapture();
        viewModel.AddMaskStroke(_currentStrokeKeepsForeground, _currentPoints.ToArray());
        _currentPoints.Clear();
        _currentPolyline = null;
        e.Handled = true;
    }

    private bool TryMapPoint(Point point, DieCutLineToolViewModel viewModel, out DieCutPointRequest normalized, out Point canvasPoint)
    {
        normalized = new DieCutPointRequest();
        canvasPoint = default;
        if (MaskEditorCanvas.ActualWidth <= 0 || MaskEditorCanvas.ActualHeight <= 0 || viewModel.SourceWidth <= 0 || viewModel.SourceHeight <= 0)
        {
            return false;
        }
        var scale = Math.Min(MaskEditorCanvas.ActualWidth / viewModel.SourceWidth, MaskEditorCanvas.ActualHeight / viewModel.SourceHeight);
        var imageWidth = viewModel.SourceWidth * scale;
        var imageHeight = viewModel.SourceHeight * scale;
        var left = (MaskEditorCanvas.ActualWidth - imageWidth) / 2;
        var top = (MaskEditorCanvas.ActualHeight - imageHeight) / 2;
        var x = (point.X - left) / imageWidth;
        var y = (point.Y - top) / imageHeight;
        if (x < 0 || x > 1 || y < 0 || y > 1)
        {
            return false;
        }
        normalized = new DieCutPointRequest { X = x, Y = y };
        canvasPoint = point;
        return true;
    }

    private void ResetDrawing()
    {
        if (MaskEditorCanvas.IsMouseCaptured)
        {
            MaskEditorCanvas.ReleaseMouseCapture();
        }
        _drawing = false;
        _currentPolyline = null;
        _currentPoints.Clear();
    }
}
