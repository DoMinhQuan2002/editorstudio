using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Views;

public partial class VideoCreatorDraftPreviewView : UserControl
{
    private readonly DispatcherTimer _playbackTimer;
    private VideoCreatorDraftPreviewViewModel? _viewModel;
    private bool _isSeeking;
    private bool _updatingPlaybackPosition;

    // ---- Direct manipulation of a cut-out on the preview (CapCut style) ----
    // Snap distance in canvas pixels (the canvas is the 1080x1920 design space).
    private const double SnapDistance = 28;
    private const double HandleHitRadius = 60;
    private enum EditDrag { None, Move, Scale }
    private EditDrag _editDrag;
    private Point _dragStart;
    private double _dragStartScale, _dragStartOffsetX, _dragStartOffsetY, _dragStartDistance;
    private VideoCreatorOverlayAdjustmentViewModel? _watchedOverlay;

    public VideoCreatorDraftPreviewView()
    {
        InitializeComponent();
        _playbackTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(120) };
        _playbackTimer.Tick += OnPlaybackTick;
        DataContextChanged += OnDataContextChanged;
        Unloaded += (_, _) =>
        {
            PreviewPlayer.Pause();
            _playbackTimer.Stop();
            _isSeeking = false;
            _viewModel?.SetIsPlaying(false);
        };
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged -= OnPreviewViewModelPropertyChanged;
            _viewModel.PlaybackSeekRequested -= OnPlaybackSeekRequested;
        }
        WatchOverlay(null);
        PreviewPlayer.Stop();
        _viewModel = e.NewValue as VideoCreatorDraftPreviewViewModel;
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged += OnPreviewViewModelPropertyChanged;
            _viewModel.PlaybackSeekRequested += OnPlaybackSeekRequested;
            WatchOverlay(_viewModel.SelectedOverlay);
        }
        _playbackTimer.Stop();
    }

    private void OnPlaybackSeekRequested(TimeSpan position)
    {
        if (_viewModel?.IsPlaybackVerified != true) return;
        PreviewPlayer.Position = TimeSpan.FromSeconds(Math.Clamp(position.TotalSeconds, 0, _viewModel.DurationSeconds));
    }

    private void OnPreviewViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(VideoCreatorDraftPreviewViewModel.IsPreviewMuted) && _viewModel is not null)
            PreviewPlayer.IsMuted = _viewModel.IsPreviewMuted;
        else if (e.PropertyName == nameof(VideoCreatorDraftPreviewViewModel.CurrentSeconds)
            && !_isSeeking && !_updatingPlaybackPosition && _viewModel?.IsPlaybackVerified == true && !_viewModel.IsPlaying)
            OnPlaybackSeekRequested(TimeSpan.FromSeconds(_viewModel.CurrentSeconds));
        else if (e.PropertyName == nameof(VideoCreatorDraftPreviewViewModel.SelectedOverlay))
            WatchOverlay(_viewModel?.SelectedOverlay);
        else if (e.PropertyName is nameof(VideoCreatorDraftPreviewViewModel.OverlayEditLayer)
                 or nameof(VideoCreatorDraftPreviewViewModel.IsOverlayEditing))
        {
            if (_viewModel?.IsOverlayEditing == true)
            {
                PreviewPlayer.Pause();
                _playbackTimer.Stop();
                _viewModel.SetIsPlaying(false);
                EditCanvas.Focus();
            }
            UpdateEditSurface();
        }
        else if (e.PropertyName == nameof(VideoCreatorDraftPreviewViewModel.PreviewVideoUri))
        {
            PreviewPlayer.Stop();
            _playbackTimer.Stop();
            _isSeeking = false;
            _viewModel?.SetIsPlaying(false);
        }
    }

    private void OnPlay(object sender, RoutedEventArgs e)
    {
        if (_viewModel?.IsPlaybackVerified != true) return;
        var requestedPosition = TimeSpan.FromSeconds(Math.Clamp(
            _viewModel.CurrentSeconds, 0, _viewModel.DurationSeconds));
        // Only an explicit Play at the end starts a new playback pass.
        if (requestedPosition.TotalSeconds >= _viewModel.DurationSeconds)
            requestedPosition = TimeSpan.Zero;
        PreviewPlayer.Position = requestedPosition;
        _viewModel.SetIsPlaying(true);
        SyncPlaybackPosition(requestedPosition);
        PreviewPlayer.Play();
        _playbackTimer.Start();
    }

    // Single play/pause control in the redesigned player bar.
    private void OnPlayPauseToggle(object sender, RoutedEventArgs e)
    {
        if (_viewModel?.IsPlaying == true) OnPause(sender, e);
        else OnPlay(sender, e);
    }

    private void OnScenesLeft(object sender, RoutedEventArgs e) =>
        SceneScroller.ScrollToHorizontalOffset(Math.Max(0, SceneScroller.HorizontalOffset - SceneScroller.ViewportWidth * 0.8));

    private void OnScenesRight(object sender, RoutedEventArgs e) =>
        SceneScroller.ScrollToHorizontalOffset(SceneScroller.HorizontalOffset + SceneScroller.ViewportWidth * 0.8);

    private void OnPause(object sender, RoutedEventArgs e)
    {
        PreviewPlayer.Pause();
        SyncPlaybackPosition(PreviewPlayer.Position);
        _viewModel?.SetIsPlaying(false);
        _playbackTimer.Stop();
    }

    private void OnSeekStarted(object sender, MouseButtonEventArgs e) => _isSeeking = true;

    private void OnSeekSliderValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (_isSeeking || _updatingPlaybackPosition || _viewModel?.IsPlaybackVerified != true || _viewModel.IsPlaying) return;
        OnPlaybackSeekRequested(TimeSpan.FromSeconds(e.NewValue));
    }

    private async void OnSeekCompleted(object sender, MouseButtonEventArgs e)
    {
        _isSeeking = false;
        if (_viewModel is null) return;
        var position = TimeSpan.FromSeconds(Math.Clamp(_viewModel.CurrentSeconds, 0, _viewModel.DurationSeconds));
        PreviewPlayer.Position = position;
        await _viewModel.SeekToAsync(position.TotalSeconds);
    }

    private void OnPreviewMediaOpened(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || !PreviewPlayer.NaturalDuration.HasTimeSpan) return;
        _viewModel.MarkPlaybackOpened(PreviewPlayer.NaturalDuration.TimeSpan);
        if (_viewModel.IsPlaybackVerified)
        {
            PreviewPlayer.IsMuted = _viewModel.IsPreviewMuted;
            PreviewPlayer.Position = TimeSpan.FromSeconds(Math.Clamp(_viewModel.CurrentSeconds, 0, _viewModel.DurationSeconds));
        }
    }

    private void OnPreviewMediaFailed(object sender, ExceptionRoutedEventArgs e)
    {
        _playbackTimer.Stop();
        _viewModel?.MarkPlaybackFailed(e.ErrorException?.Message ?? "WPF MediaElement báo lỗi.");
    }

    private void OnPreviewMediaEnded(object sender, RoutedEventArgs e)
    {
        // Keep the final frame and timestamp. Rewinding here can restart a
        // MediaElement while the UI already reports that playback has stopped.
        PreviewPlayer.Pause();
        _playbackTimer.Stop();
        _isSeeking = false;
        if (_viewModel is not null)
            SyncPlaybackPosition(TimeSpan.FromSeconds(_viewModel.DurationSeconds));
        _viewModel?.SetIsPlaying(false);
    }

    private void OnPlaybackTick(object? sender, EventArgs e)
    {
        if (_viewModel is null || _isSeeking || !_viewModel.IsPlaying) return;
        SyncPlaybackPosition(PreviewPlayer.Position);
    }

    private void SyncPlaybackPosition(TimeSpan position)
    {
        _updatingPlaybackPosition = true;
        try { _viewModel?.SetPlaybackPosition(position); }
        finally { _updatingPlaybackPosition = false; }
    }

    private async void OnFullscreen(object sender, RoutedEventArgs e)
    {
        if (_viewModel?.IsPlaybackVerified != true || _viewModel.PreviewVideoUri is null) return;
        var wasPlaying = _viewModel.IsPlaying;
        var resumeAt = TimeSpan.FromSeconds(Math.Clamp(_viewModel.CurrentSeconds, 0, _viewModel.DurationSeconds));
        PreviewPlayer.Pause();
        _viewModel.SetIsPlaying(false);
        _playbackTimer.Stop();
        await _viewModel.RefreshStillFrameAsync(resumeAt.TotalSeconds);

        var window = new Window
        {
            Title = "Video preview",
            WindowStyle = WindowStyle.None,
            WindowState = WindowState.Maximized,
            Background = Brushes.Black,
            Topmost = true,
            Owner = Window.GetWindow(this),
            Focusable = true,
        };
        var fullscreenImage = new Image { Stretch = Stretch.Uniform };
        fullscreenImage.SetBinding(Image.SourceProperty, new Binding(nameof(VideoCreatorDraftPreviewViewModel.PreviewFrame))
        {
            Source = _viewModel,
        });
        var fullscreenRoot = CreateFullscreenContent(fullscreenImage, out var closeButton, out var playButton);
        window.Content = fullscreenRoot;
        var fullscreenIsPlaying = wasPlaying;
        playButton.Content = fullscreenIsPlaying ? "Ⅱ" : "▶";
        var fullscreenFrameTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(600) };
        var frameUpdatePending = false;
        fullscreenFrameTimer.Tick += async (_, _) =>
        {
            if (!fullscreenIsPlaying || frameUpdatePending || _viewModel is null) return;
            frameUpdatePending = true;
            try
            {
                var position = PreviewPlayer.Position;
                _viewModel.SetPlaybackPosition(position);
                await _viewModel.RefreshStillFrameAsync(position.TotalSeconds);
            }
            finally { frameUpdatePending = false; }
        };

        var fullscreenViewModel = _viewModel;
        PropertyChangedEventHandler syncFullscreenPlayback = (_, args) =>
        {
            if (args.PropertyName != nameof(VideoCreatorDraftPreviewViewModel.IsPlaying)) return;
            fullscreenIsPlaying = fullscreenViewModel.IsPlaying;
            playButton.Content = fullscreenIsPlaying ? "Ⅱ" : "▶";
            if (fullscreenIsPlaying) fullscreenFrameTimer.Start();
            else fullscreenFrameTimer.Stop();
        };
        fullscreenViewModel.PropertyChanged += syncFullscreenPlayback;

        closeButton.Click += (_, _) => window.Close();
        playButton.Click += (_, _) =>
        {
            fullscreenIsPlaying = !fullscreenIsPlaying;
            if (fullscreenIsPlaying)
            {
                OnPlay(sender, e);
                fullscreenFrameTimer.Start();
                playButton.Content = "Ⅱ";
            }
            else
            {
                PreviewPlayer.Pause();
                _viewModel?.SetPlaybackPosition(PreviewPlayer.Position);
                _viewModel?.SetIsPlaying(false);
                _playbackTimer.Stop();
                fullscreenFrameTimer.Stop();
                playButton.Content = "▶";
            }
        };
        window.PreviewKeyDown += (_, args) => { if (args.Key == Key.Escape) window.Close(); };
        if (fullscreenIsPlaying)
        {
            PreviewPlayer.Play();
            PreviewPlayer.Position = resumeAt;
            _viewModel.SetIsPlaying(true);
            _playbackTimer.Start();
            fullscreenFrameTimer.Start();
        }
        try { window.ShowDialog(); }
        finally
        {
            fullscreenViewModel.PropertyChanged -= syncFullscreenPlayback;
            fullscreenFrameTimer.Stop();
        }
        var finalPosition = PreviewPlayer.NaturalDuration.HasTimeSpan ? PreviewPlayer.Position : resumeAt;
        PreviewPlayer.Pause();
        _viewModel.SetPlaybackPosition(finalPosition);
        await _viewModel.RefreshStillFrameAsync(finalPosition.TotalSeconds);
        if (fullscreenIsPlaying)
        {
            PreviewPlayer.Play();
            PreviewPlayer.Position = finalPosition;
            _viewModel.SetIsPlaying(true);
            _playbackTimer.Start();
        }
        else
        {
            _viewModel.SetIsPlaying(false);
            _playbackTimer.Stop();
        }
    }

    private static Grid CreateFullscreenContent(Image image, out Button closeButton, out Button playButton)
    {
        var root = new Grid { Background = Brushes.Black };
        root.Children.Add(image);
        var controls = new DockPanel
        {
            LastChildFill = false,
            VerticalAlignment = VerticalAlignment.Top,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            Background = new SolidColorBrush(Color.FromArgb(155, 20, 20, 25)),
            Margin = new Thickness(18),
        };
        closeButton = new Button { Content = "×", FontSize = 24, Width = 48, Height = 44, HorizontalAlignment = HorizontalAlignment.Right };
        DockPanel.SetDock(closeButton, Dock.Right);
        controls.Children.Add(closeButton);
        playButton = new Button { Content = "Ⅱ", FontSize = 18, Width = 48, Height = 44, HorizontalAlignment = HorizontalAlignment.Left };
        DockPanel.SetDock(playButton, Dock.Left);
        controls.Children.Add(playButton);
        root.Children.Add(controls);
        var hint = new TextBlock
        {
            Text = "Esc để đóng",
            Foreground = Brushes.White,
            FontSize = 12,
            HorizontalAlignment = HorizontalAlignment.Right,
            VerticalAlignment = VerticalAlignment.Bottom,
            Margin = new Thickness(20),
        };
        root.Children.Add(hint);
        return root;
    }

    private async void OnPreviewSurfaceClick(object sender, MouseButtonEventArgs e)
    {
        if (_viewModel is null) return;
        e.Handled = true;
        if (_viewModel.IsPlaying) _viewModel.SetPlaybackPosition(PreviewPlayer.Position);
        PreviewPlayer.Pause();
        _playbackTimer.Stop();
        _viewModel.SetIsPlaying(false);
        await _viewModel.BeginOverlayEditAtCurrentTimeAsync();
    }

    private void WatchOverlay(VideoCreatorOverlayAdjustmentViewModel? overlay)
    {
        if (_watchedOverlay is not null) _watchedOverlay.PropertyChanged -= OnWatchedOverlayChanged;
        _watchedOverlay = overlay;
        if (_watchedOverlay is not null) _watchedOverlay.PropertyChanged += OnWatchedOverlayChanged;
        UpdateEditSurface();
    }

    // Sliders and mouse both change the item; redraw on every change so the
    // preview follows in real time.
    private void OnWatchedOverlayChanged(object? sender, PropertyChangedEventArgs e) => UpdateEditSurface();

    private OverlayEditLayer? CurrentEditLayer =>
        _viewModel is { IsOverlayEditing: true, OverlayEditLayer: { } layer, SelectedOverlay: { } overlay }
        && layer.ClipId == overlay.ClipId ? layer : null;

    /// <summary>Overlay image rectangle on the canvas for the given manual values.</summary>
    private static Rect LayerRect(OverlayEditLayer layer, double scale, double offsetX, double offsetY)
    {
        double w = layer.CanvasWidth, h = layer.CanvasHeight;
        var centreX = (layer.BaseLeft + layer.BaseWidth / 2 + offsetX) * w;
        var centreY = (layer.BaseTop + layer.BaseHeight / 2 + offsetY) * h;
        var width = layer.BaseWidth * w * scale;
        var height = layer.BaseHeight * h * scale;
        return new Rect(centreX - width / 2, centreY - height / 2, Math.Max(1, width), Math.Max(1, height));
    }

    /// <summary>Visible subject rectangle on the canvas: what the user sees and grabs.</summary>
    private static Rect SubjectRect(OverlayEditLayer layer, Rect layerRect)
    {
        var box = layer.SubjectBox;
        return new Rect(layerRect.X + box[0] * layerRect.Width, layerRect.Y + box[1] * layerRect.Height,
            Math.Max(1, (box[2] - box[0]) * layerRect.Width), Math.Max(1, (box[3] - box[1]) * layerRect.Height));
    }

    private void UpdateEditSurface(bool showVerticalGuide = false, bool showHorizontalGuide = false)
    {
        var layer = CurrentEditLayer;
        if (layer is null || _viewModel?.SelectedOverlay is not { } overlay)
        {
            EditBackground.Source = null;
            EditLayerImage.Source = null;
            SetEditChromeVisibility(Visibility.Collapsed);
            GuideVertical.Visibility = GuideHorizontal.Visibility = Visibility.Collapsed;
            return;
        }
        EditCanvas.Width = layer.CanvasWidth;
        EditCanvas.Height = layer.CanvasHeight;
        EditBackground.Width = layer.CanvasWidth;
        EditBackground.Height = layer.CanvasHeight;
        EditBackground.Source = layer.Background;
        EditLayerImage.Source = layer.Layer;

        var rect = LayerRect(layer, overlay.Scale, overlay.OffsetX, overlay.OffsetY);
        Place(EditLayerImage, rect);
        var subject = SubjectRect(layer, rect);
        Place(SelectionBox, subject);
        PlaceHandle(HandleTopLeft, subject.TopLeft);
        PlaceHandle(HandleTopRight, subject.TopRight);
        PlaceHandle(HandleBottomLeft, subject.BottomLeft);
        PlaceHandle(HandleBottomRight, subject.BottomRight);
        SetEditChromeVisibility(Visibility.Visible);

        GuideVertical.X1 = GuideVertical.X2 = layer.CanvasWidth / 2.0;
        GuideVertical.Y1 = 0; GuideVertical.Y2 = layer.CanvasHeight;
        GuideHorizontal.Y1 = GuideHorizontal.Y2 = layer.CanvasHeight / 2.0;
        GuideHorizontal.X1 = 0; GuideHorizontal.X2 = layer.CanvasWidth;
        GuideVertical.Visibility = showVerticalGuide ? Visibility.Visible : Visibility.Collapsed;
        GuideHorizontal.Visibility = showHorizontalGuide ? Visibility.Visible : Visibility.Collapsed;
    }

    private void SetEditChromeVisibility(Visibility visibility)
    {
        SelectionBox.Visibility = visibility;
        HandleTopLeft.Visibility = HandleTopRight.Visibility = visibility;
        HandleBottomLeft.Visibility = HandleBottomRight.Visibility = visibility;
    }

    private static void Place(FrameworkElement element, Rect rect)
    {
        Canvas.SetLeft(element, rect.X);
        Canvas.SetTop(element, rect.Y);
        element.Width = rect.Width;
        element.Height = rect.Height;
    }

    private static void PlaceHandle(FrameworkElement handle, Point centre)
    {
        Canvas.SetLeft(handle, centre.X - handle.Width / 2);
        Canvas.SetTop(handle, centre.Y - handle.Height / 2);
    }

    private void OnEditMouseDown(object sender, MouseButtonEventArgs e)
    {
        var layer = CurrentEditLayer;
        if (layer is null || _viewModel?.SelectedOverlay is not { } overlay) return;
        EditCanvas.Focus();
        var point = e.GetPosition(EditCanvas);
        var rect = LayerRect(layer, overlay.Scale, overlay.OffsetX, overlay.OffsetY);
        var subject = SubjectRect(layer, rect);
        var nearCorner = new[] { subject.TopLeft, subject.TopRight, subject.BottomLeft, subject.BottomRight }
            .Any(corner => (corner - point).Length <= HandleHitRadius);
        if (nearCorner) _editDrag = EditDrag.Scale;
        else if (subject.Contains(point) || rect.Contains(point)) _editDrag = EditDrag.Move;
        else return;
        _dragStart = point;
        _dragStartScale = overlay.Scale;
        _dragStartOffsetX = overlay.OffsetX;
        _dragStartOffsetY = overlay.OffsetY;
        var centre = new Point(rect.X + rect.Width / 2, rect.Y + rect.Height / 2);
        _dragStartDistance = Math.Max(1, (point - centre).Length);
        EditCanvas.CaptureMouse();
        e.Handled = true;
    }

    private void OnEditMouseMove(object sender, MouseEventArgs e)
    {
        var layer = CurrentEditLayer;
        if (layer is null || _viewModel?.SelectedOverlay is not { } overlay) return;
        var point = e.GetPosition(EditCanvas);
        if (_editDrag == EditDrag.None)
        {
            var rect = LayerRect(layer, overlay.Scale, overlay.OffsetX, overlay.OffsetY);
            var subject = SubjectRect(layer, rect);
            var nearCorner = new[] { subject.TopLeft, subject.TopRight, subject.BottomLeft, subject.BottomRight }
                .Any(corner => (corner - point).Length <= HandleHitRadius);
            EditCanvas.Cursor = nearCorner ? Cursors.SizeNWSE : rect.Contains(point) ? Cursors.SizeAll : Cursors.Arrow;
            return;
        }
        if (_editDrag == EditDrag.Scale)
        {
            var startRect = LayerRect(layer, _dragStartScale, _dragStartOffsetX, _dragStartOffsetY);
            var centre = new Point(startRect.X + startRect.Width / 2, startRect.Y + startRect.Height / 2);
            var factor = Math.Max(1, (point - centre).Length) / _dragStartDistance;
            overlay.SetPlacement(_dragStartScale * factor, overlay.OffsetX, overlay.OffsetY);
            return;
        }
        // Move: raw position follows the mouse; snapping is applied on top of it
        // so the image can be pulled away from the centre again.
        var offsetX = _dragStartOffsetX + (point.X - _dragStart.X) / layer.CanvasWidth;
        var offsetY = _dragStartOffsetY + (point.Y - _dragStart.Y) / layer.CanvasHeight;
        var snapX = false;
        var snapY = false;
        if (!Keyboard.IsKeyDown(Key.LeftAlt) && !Keyboard.IsKeyDown(Key.RightAlt))
        {
            var subject = SubjectRect(layer, LayerRect(layer, overlay.Scale, offsetX, offsetY));
            var dx = layer.CanvasWidth / 2.0 - (subject.X + subject.Width / 2);
            var dy = layer.CanvasHeight / 2.0 - (subject.Y + subject.Height / 2);
            if (Math.Abs(dx) <= SnapDistance) { offsetX += dx / layer.CanvasWidth; snapX = true; }
            if (Math.Abs(dy) <= SnapDistance) { offsetY += dy / layer.CanvasHeight; snapY = true; }
        }
        overlay.SetPlacement(overlay.Scale, offsetX, offsetY);
        UpdateEditSurface(snapX, snapY);
    }

    private void OnEditMouseUp(object sender, MouseButtonEventArgs e)
    {
        if (_editDrag == EditDrag.None) return;
        _editDrag = EditDrag.None;
        EditCanvas.ReleaseMouseCapture();
        UpdateEditSurface();
        e.Handled = true;
    }

    private void OnEditLostCapture(object sender, MouseEventArgs e)
    {
        if (_editDrag == EditDrag.None) return;
        _editDrag = EditDrag.None;
        UpdateEditSurface();
    }

    private void OnEditMouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (CurrentEditLayer is null || _viewModel?.SelectedOverlay is not { } overlay) return;
        var factor = Math.Pow(1.08, e.Delta / 120.0);
        overlay.SetPlacement(overlay.Scale * factor, overlay.OffsetX, overlay.OffsetY);
        e.Handled = true;
    }

    // Arrow keys nudge by one canvas pixel (ten with Shift).
    private void OnEditKeyDown(object sender, KeyEventArgs e)
    {
        var layer = CurrentEditLayer;
        if (layer is null || _viewModel?.SelectedOverlay is not { } overlay) return;
        var step = Keyboard.Modifiers.HasFlag(ModifierKeys.Shift) ? 10.0 : 1.0;
        var (dx, dy) = e.Key switch
        {
            Key.Left => (-step, 0.0), Key.Right => (step, 0.0),
            Key.Up => (0.0, -step), Key.Down => (0.0, step),
            _ => (0.0, 0.0),
        };
        if (dx == 0 && dy == 0) return;
        overlay.SetPlacement(overlay.Scale, overlay.OffsetX + dx / layer.CanvasWidth, overlay.OffsetY + dy / layer.CanvasHeight);
        e.Handled = true;
    }
}
