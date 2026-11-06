using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media.Effects;
using System.Windows.Input;
using System.Windows.Media;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Views;

/// <summary>
/// Media selection with drag and drop: drag a library item onto a selected
/// item to replace it, drag selected items among themselves to reorder, or drop
/// onto empty space in the strip to append.
/// </summary>
public partial class MediaSelectionView : UserControl
{
    private static readonly Brush DropHighlight = new SolidColorBrush(Color.FromRgb(0x68, 0x50, 0xFF));
    private Point _dragStart;
    private SelectionMediaItem? _dragItem;
    private bool _dragHappened;
    private Point? _libraryStart;
    private SelectionMediaItem? _libraryClickItem;
    private HashSet<SelectionMediaItem> _libraryMarkBaseline = [];
    private ModifierKeys _libraryModifiers;
    private bool _libraryMarqueeActive;
    private bool _libraryDragPending;
    private Popup? _dragGhost;

    private void OnLibraryMouseDown(object sender, MouseButtonEventArgs e)
    {
        if (ViewModel is not { IsBusy: false } vm) return;
        for (var node = e.OriginalSource as DependencyObject; node is not null; node = VisualTreeHelper.GetParent(node))
            if (node is Button { Tag: "AddToSequence" }) return;
        var modifiers = Keyboard.Modifiers;
        // Leave the scrollbar available while multi-selecting.
        for (var node = e.OriginalSource as DependencyObject; node is not null; node = VisualTreeHelper.GetParent(node))
            if (node is System.Windows.Controls.Primitives.ScrollBar) return;
        vm.IsBulkSelecting = true;
        _libraryModifiers = modifiers;
        _libraryStart = e.GetPosition(LibrarySurface);
        _libraryClickItem = (e.OriginalSource as FrameworkElement)?.DataContext as SelectionMediaItem;
        _libraryMarkBaseline = modifiers.HasFlag(ModifierKeys.Control)
            ? vm.Media.Where(item => item.IsLibraryMarked).ToHashSet() : [];
        _libraryMarqueeActive = false;
        _libraryDragPending = _libraryClickItem is not null;
        LibrarySurface.Focus();
        LibrarySurface.CaptureMouse();
        e.Handled = true;
    }

    private void OnLibraryMouseMove(object sender, MouseEventArgs e)
    {
        if (_libraryStart is not { } start || ViewModel is not { IsBusy: false } vm) return;
        var point = e.GetPosition(LibrarySurface);
        if (!_libraryMarqueeActive && (point - start).Length < SystemParameters.MinimumHorizontalDragDistance) return;
        if (_libraryDragPending && _libraryClickItem is { } pressed)
        {
            // Pressing on a media and moving drags media instead of drawing a box:
            // the highlighted (bôi đen) media if any, otherwise the one under the cursor.
            var highlighted = vm.Media.Where(item => item.IsLibraryMarked).ToList();
            List<SelectionMediaItem> items = highlighted.Count > 0 ? highlighted : [pressed];
            _libraryStart = null;
            _libraryDragPending = false;
            LibrarySurface.ReleaseMouseCapture();
            StartDrag(LibrarySurface, items, DragDropEffects.Copy | DragDropEffects.Move);
            e.Handled = true;
            return;
        }
        _libraryMarqueeActive = true;
        var bounds = new Rect(start, point);
        Canvas.SetLeft(LibraryMarquee, bounds.Left); Canvas.SetTop(LibraryMarquee, bounds.Top);
        LibraryMarquee.Width = bounds.Width; LibraryMarquee.Height = bounds.Height;
        LibraryMarquee.Visibility = Visibility.Visible;
        var marked = new HashSet<SelectionMediaItem>(_libraryMarkBaseline);
        foreach (var item in vm.Media)
        {
            if (LibraryItems.ItemContainerGenerator.ContainerFromItem(item) is not FrameworkElement container) continue;
            var itemBounds = container.TransformToAncestor(LibrarySurface).TransformBounds(new Rect(container.RenderSize));
            if (bounds.IntersectsWith(itemBounds)) marked.Add(item);
        }
        vm.SetLibraryMarks(marked);
        e.Handled = true;
    }

    private void OnLibraryMouseUp(object sender, MouseButtonEventArgs e)
    {
        if (_libraryStart is null) return;
        if (!_libraryMarqueeActive && _libraryClickItem is { } item)
            ViewModel?.MarkLibraryItem(item, _libraryModifiers.HasFlag(ModifierKeys.Shift),
                _libraryModifiers.HasFlag(ModifierKeys.Control));
        else if (!_libraryMarqueeActive) ViewModel?.SetLibraryMarks([]);
        _libraryStart = null;
        _libraryDragPending = false;
        LibraryMarquee.Visibility = Visibility.Collapsed;
        LibrarySurface.ReleaseMouseCapture();
        e.Handled = true;
    }

    private void OnLibraryLostCapture(object sender, MouseEventArgs e)
    {
        _libraryStart = null;
        LibraryMarquee.Visibility = Visibility.Collapsed;
    }

    private void OnLibraryKeyDown(object sender, KeyEventArgs e)
    {
        if (ViewModel is not { IsBusy: false } vm) return;
        if (e.Key == Key.A && Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
            vm.MarkAllLibraryCommand.Execute(null);
        else if (e.Key == Key.Delete && vm.DeleteLibraryCommand.CanExecute(null))
            vm.DeleteLibraryCommand.Execute(null);
        else if (e.Key == Key.Escape && vm.IsBulkSelecting) vm.IsBulkSelecting = false;
        else return;
        e.Handled = true;
    }

    public MediaSelectionView() => InitializeComponent();

    private MediaSelectionViewModel? ViewModel => DataContext as MediaSelectionViewModel;

    private void OnDragSourceMouseDown(object sender, MouseButtonEventArgs e)
    {
        _dragStart = e.GetPosition(this);
        _dragItem = (sender as FrameworkElement)?.DataContext as SelectionMediaItem;
        _dragHappened = false;
    }

    private void OnDragSourceMouseMove(object sender, MouseEventArgs e)
    {
        if (_dragItem is null || e.LeftButton != MouseButtonState.Pressed || sender is not DependencyObject source) return;
        var delta = e.GetPosition(this) - _dragStart;
        if (Math.Abs(delta.X) < SystemParameters.MinimumHorizontalDragDistance
            && Math.Abs(delta.Y) < SystemParameters.MinimumVerticalDragDistance) return;
        var item = _dragItem;
        _dragItem = null;
        _dragHappened = true;
        StartDrag(source, [item], DragDropEffects.Move | DragDropEffects.Copy);
    }

    // A drag must not also count as a click (which would toggle the selection).
    private void OnDragSourceMouseUp(object sender, MouseButtonEventArgs e)
    {
        _dragItem = null;
        if (!_dragHappened) return;
        _dragHappened = false;
        e.Handled = true;
    }

    private static SelectionMediaItem? DraggedItem(DragEventArgs e) => DraggedItems(e).FirstOrDefault();

    private static IReadOnlyList<SelectionMediaItem> DraggedItems(DragEventArgs e)
    {
        if (e.Data.GetDataPresent(typeof(SelectionMediaItem[])) && e.Data.GetData(typeof(SelectionMediaItem[])) is SelectionMediaItem[] many)
            return many;
        return e.Data.GetDataPresent(typeof(SelectionMediaItem)) && e.Data.GetData(typeof(SelectionMediaItem)) is SelectionMediaItem one
            ? [one] : [];
    }

    // ---- Drag with a floating ghost that follows the cursor ----
    private void StartDrag(DependencyObject source, IReadOnlyList<SelectionMediaItem> items, DragDropEffects effects)
    {
        if (items.Count == 0) return;
        var data = new DataObject();
        data.SetData(typeof(SelectionMediaItem), items[0]);
        data.SetData(typeof(SelectionMediaItem[]), items.ToArray());
        ShowGhost(items);
        foreach (var item in items) item.IsDragging = true;
        GiveFeedbackEventHandler feedback = (_, _) => MoveGhost();
        if (source is UIElement element) element.GiveFeedback += feedback;
        try
        {
            DragDrop.DoDragDrop(source, data, effects);
        }
        finally
        {
            if (source is UIElement e2) e2.GiveFeedback -= feedback;
            foreach (var item in items) item.IsDragging = false;
            HideGhost();
            ResetStripHighlight();
        }
    }

    private void ShowGhost(IReadOnlyList<SelectionMediaItem> items)
    {
        var stack = new Grid { Width = 128, Height = 112 };
        var shown = items.Take(3).ToList();
        for (var i = shown.Count - 1; i >= 0; i--)
        {
            var card = new Border
            {
                Width = 96, Height = 96, CornerRadius = new CornerRadius(12),
                BorderBrush = Brushes.White, BorderThickness = new Thickness(3),
                HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(i * 10, i * 6, 0, 0),
                RenderTransformOrigin = new Point(0.5, 0.5),
                RenderTransform = new RotateTransform((i - 1) * 5),
                Background = shown[i].Thumbnail is ImageSource thumb
                    ? new ImageBrush(thumb) { Stretch = Stretch.UniformToFill }
                    : new SolidColorBrush(Color.FromRgb(0xEC, 0xED, 0xF3)),
                Effect = new DropShadowEffect { BlurRadius = 14, ShadowDepth = 4, Opacity = 0.35 },
            };
            stack.Children.Add(card);
        }
        var badge = new Border
        {
            MinWidth = 28, Height = 28, CornerRadius = new CornerRadius(14), Padding = new Thickness(7, 0, 7, 0),
            Background = DropHighlight, BorderBrush = Brushes.White, BorderThickness = new Thickness(2),
            HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top,
            Child = new TextBlock
            {
                Text = items.Count.ToString(), Foreground = Brushes.White, FontWeight = FontWeights.SemiBold,
                FontSize = 13, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
            },
        };
        stack.Children.Add(badge);
        _dragGhost = new Popup
        {
            AllowsTransparency = true, IsHitTestVisible = false, Placement = PlacementMode.Absolute,
            Child = new Border { Opacity = 0.92, Child = stack, IsHitTestVisible = false },
            PlacementTarget = this,
        };
        MoveGhost();
        _dragGhost.IsOpen = true;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct NativePoint { public int X; public int Y; }

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out NativePoint point);

    private void MoveGhost()
    {
        if (_dragGhost is null || !GetCursorPos(out var cursor)) return;
        var source = PresentationSource.FromVisual(this);
        var point = new Point(cursor.X, cursor.Y);
        if (source?.CompositionTarget is { } target) point = target.TransformFromDevice.Transform(point);
        _dragGhost.HorizontalOffset = point.X + 14;
        _dragGhost.VerticalOffset = point.Y + 10;
    }

    private void HideGhost()
    {
        if (_dragGhost is null) return;
        _dragGhost.IsOpen = false;
        _dragGhost = null;
    }

    private void ResetStripHighlight()
    {
        SelectedStrip.Background = new SolidColorBrush(Color.FromRgb(0xFA, 0xF9, 0xFE));
        SelectedStrip.BorderBrush = null;
        SelectedStrip.BorderThickness = new Thickness(0);
    }

    private void OnSelectedDragEnter(object sender, DragEventArgs e)
    {
        if (sender is Border border && DraggedItem(e) is not null) border.BorderBrush = DropHighlight;
    }

    private void OnSelectedDragOver(object sender, DragEventArgs e)
    {
        e.Effects = DraggedItem(e) is null ? DragDropEffects.None : DragDropEffects.Move;
        MoveGhost();
        e.Handled = true;
    }

    private void OnSelectedDragLeave(object sender, DragEventArgs e)
    {
        if (sender is Border border) border.BorderBrush = Brushes.Transparent;
    }

    private void OnSelectedDrop(object sender, DragEventArgs e)
    {
        if (sender is Border border) border.BorderBrush = Brushes.Transparent;
        var items = DraggedItems(e);
        if (items.Count == 0 || (sender as FrameworkElement)?.DataContext is not SelectionMediaItem target) return;
        ViewModel?.DropMany(items, target);
        SelectedStrip.BorderBrush = null;
        e.Handled = true;
    }

    private void OnStripDragOver(object sender, DragEventArgs e)
    {
        var valid = DraggedItem(e) is not null;
        e.Effects = valid ? DragDropEffects.Copy : DragDropEffects.None;
        if (valid)
        {
            // Drop zone lights up while media is held over it.
            SelectedStrip.Background = new SolidColorBrush(Color.FromRgb(0xEE, 0xEB, 0xFF));
            SelectedStrip.BorderBrush = DropHighlight;
            SelectedStrip.BorderThickness = new Thickness(2);
        }
        MoveGhost();
        e.Handled = true;
    }

    private void OnStripDragLeave(object sender, DragEventArgs e) => ResetStripHighlight();

    private void OnStripDrop(object sender, DragEventArgs e)
    {
        ResetStripHighlight();
        var items = DraggedItems(e);
        if (items.Count > 0) ViewModel?.DropMany(items, null);
        e.Handled = true;
    }

    // ---- Large preview: previous/next, zoom, fullscreen ----
    private void StepMedia(int step)
    {
        if (ViewModel is not { } vm || vm.Media.Count == 0) return;
        var index = vm.ActiveMedia is null ? -1 : vm.Media.IndexOf(vm.ActiveMedia);
        index = index < 0 ? 0 : (index + step + vm.Media.Count) % vm.Media.Count;
        vm.FocusCommand.Execute(vm.Media[index]);
        SetZoom(1);
    }

    private void OnPreviousMedia(object sender, RoutedEventArgs e) => StepMedia(-1);
    private void OnNextMedia(object sender, RoutedEventArgs e) => StepMedia(1);
    private void OnZoomIn(object sender, RoutedEventArgs e) => SetZoom(PreviewZoom.ScaleX + 0.25);
    private void OnZoomOut(object sender, RoutedEventArgs e) => SetZoom(PreviewZoom.ScaleX - 0.25);

    private void SetZoom(double value)
    {
        value = Math.Clamp(value, 0.5, 3);
        PreviewZoom.ScaleX = PreviewZoom.ScaleY = value;
        ZoomLabel.Text = $"{value * 100:0}%";
    }

    private void OnPreviewFullscreen(object sender, RoutedEventArgs e)
    {
        if (LargePreview.Source is null) return;
        var window = new Window
        {
            Owner = Window.GetWindow(this),
            WindowStyle = WindowStyle.None,
            WindowState = WindowState.Maximized,
            Background = Brushes.Black,
            Content = new Image { Source = LargePreview.Source, Stretch = Stretch.Uniform },
        };
        window.KeyDown += (_, args) => { if (args.Key == Key.Escape) window.Close(); };
        window.MouseLeftButtonUp += (_, _) => window.Close();
        window.ShowDialog();
    }

    private void OnStripRight(object sender, RoutedEventArgs e) =>
        SelectedStrip.ScrollToHorizontalOffset(SelectedStrip.HorizontalOffset + 240);
}
