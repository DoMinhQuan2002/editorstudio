using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace MediaStudio.Desktop.Views;

/// <summary>
/// "Chọn media — Xử lý — Chỉnh sửa — Xuất" stepper from the Video Editor redesign.
/// Steps before <see cref="CurrentStep"/> show a filled purple check, the current
/// step a filled purple number, later steps a grey number.
/// </summary>
public sealed class WizardStepper : ContentControl
{
    public static readonly DependencyProperty CurrentStepProperty = DependencyProperty.Register(
        nameof(CurrentStep), typeof(int), typeof(WizardStepper),
        new PropertyMetadata(1, (d, _) => ((WizardStepper)d).Rebuild()));

    public static readonly DependencyProperty StepsProperty = DependencyProperty.Register(
        nameof(Steps), typeof(string), typeof(WizardStepper),
        new PropertyMetadata("Chọn media|Xử lý|Chỉnh sửa|Xuất", (d, _) => ((WizardStepper)d).Rebuild()));

    private static readonly Brush Primary = Frozen(Color.FromRgb(0x5A, 0x4C, 0xFA));
    private static readonly Brush PrimaryText = Frozen(Color.FromRgb(0x5A, 0x4C, 0xFA));
    private static readonly Brush DoneText = Frozen(Color.FromRgb(0x4B, 0x4F, 0x63));
    private static readonly Brush FutureCircle = Frozen(Color.FromRgb(0xE4, 0xE6, 0xEE));
    private static readonly Brush FutureText = Frozen(Color.FromRgb(0x8B, 0x8F, 0xA3));
    private static readonly Brush Line = Frozen(Color.FromRgb(0xDD, 0xDF, 0xE8));
    private static readonly Brush LineDone = Frozen(Color.FromRgb(0xC9, 0xC3, 0xFB));

    public WizardStepper()
    {
        Focusable = false;
        IsTabStop = false;
        Rebuild();
    }

    /// <summary>1-based index of the active step.</summary>
    public int CurrentStep { get => (int)GetValue(CurrentStepProperty); set => SetValue(CurrentStepProperty, value); }

    /// <summary>Step names separated by '|'.</summary>
    public string Steps { get => (string)GetValue(StepsProperty); set => SetValue(StepsProperty, value); }

    private static Brush Frozen(Color color)
    {
        var brush = new SolidColorBrush(color);
        brush.Freeze();
        return brush;
    }

    private void Rebuild()
    {
        var names = (Steps ?? "").Split('|', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        var panel = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
        for (var index = 0; index < names.Length; index++)
        {
            var step = index + 1;
            var done = step < CurrentStep;
            var current = step == CurrentStep;
            if (index > 0)
            {
                panel.Children.Add(new Border
                {
                    Width = 46, Height = 2, CornerRadius = new CornerRadius(1), Margin = new Thickness(14, 0, 14, 0),
                    Background = done || current ? LineDone : Line, VerticalAlignment = VerticalAlignment.Center,
                });
            }
            var circle = new Border
            {
                Width = 34, Height = 34, CornerRadius = new CornerRadius(17),
                Background = done || current ? Primary : FutureCircle, VerticalAlignment = VerticalAlignment.Center,
                Child = new TextBlock
                {
                    Text = done ? "" : step.ToString(),
                    FontFamily = done ? new FontFamily("Segoe Fluent Icons, Segoe MDL2 Assets") : new FontFamily("Segoe UI"),
                    FontSize = done ? 15 : 15, FontWeight = FontWeights.SemiBold,
                    Foreground = done || current ? Brushes.White : FutureText,
                    HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
                },
            };
            panel.Children.Add(circle);
            panel.Children.Add(new TextBlock
            {
                Text = names[index], Margin = new Thickness(10, 0, 0, 0), FontSize = 15,
                FontWeight = current ? FontWeights.SemiBold : FontWeights.Normal,
                Foreground = current ? PrimaryText : done ? DoneText : FutureText,
                VerticalAlignment = VerticalAlignment.Center,
            });
        }
        Content = panel;
    }
}
