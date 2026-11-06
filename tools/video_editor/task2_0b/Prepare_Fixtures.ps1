param(
    [string]$FixtureDirectory = 'D:\MediaStudioTask2Validation_20261021_1328\task2-0b\fixtures'
)

$ErrorActionPreference = 'Stop'
$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$fontPath = 'C:\Windows\Fonts\arial.ttf'
$fontFile = 'C\:/Windows/Fonts/arial.ttf'
if (-not (Test-Path -LiteralPath $fontPath)) {
    throw "Không tìm thấy font Arial để tạo nhãn fixture: $fontPath"
}

if (Test-Path -LiteralPath $FixtureDirectory) {
    $existing = Get-ChildItem -LiteralPath $FixtureDirectory -Force
    if ($existing.Count -gt 0) {
        throw "Thư mục fixture đã có dữ liệu, không ghi đè: $FixtureDirectory"
    }
} else {
    New-Item -ItemType Directory -Path $FixtureDirectory -Force | Out-Null
}

function Invoke-FixtureFfmpeg([string[]]$Arguments) {
    & $ffmpeg @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "FFmpeg thất bại (exit $LASTEXITCODE): $($Arguments -join ' ')"
    }
}

$base = @('-hide_banner', '-v', 'error', '-nostdin', '-n')
$videoCommon = @('-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30',
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart')
$a = Join-Path $FixtureDirectory '01_VIDEO_A_6s_blue.mp4'
$b = Join-Path $FixtureDirectory '02_VIDEO_B_4s_orange.mp4'
$c = Join-Path $FixtureDirectory '03_VIDEO_C_6s_with_audio.mp4'
$png = Join-Path $FixtureDirectory '04_IMAGE_PNG_green.png'
$jpg = Join-Path $FixtureDirectory '05_IMAGE_JPG_purple.jpg'
$mp3 = Join-Path $FixtureDirectory '06_AUDIO_MP3_440Hz_8s.mp3'
$wav = Join-Path $FixtureDirectory '07_AUDIO_WAV_markers_0p5_2p5_5s.wav'

$vfA = "drawbox=x=28:y=190:w=304:h=260:color=white@0.18:t=fill,drawtext=fontfile='$fontFile':text='VIDEO A':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=280,drawtext=fontfile='$fontFile':text='6 seconds':fontcolor=white:fontsize=20:x=(w-text_w)/2:y=332"
$vfB = "drawbox=x=28:y=190:w=304:h=260:color=black@0.15:t=fill,drawtext=fontfile='$fontFile':text='VIDEO B':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=280,drawtext=fontfile='$fontFile':text='4 seconds':fontcolor=white:fontsize=20:x=(w-text_w)/2:y=332"
$vfC = "drawbox=x=28:y=190:w=304:h=260:color=white@0.18:t=fill,drawtext=fontfile='$fontFile':text='VIDEO C + AUDIO':fontcolor=white:fontsize=27:x=(w-text_w)/2:y=292"

Invoke-FixtureFfmpeg ($base + @('-f', 'lavfi', '-i', 'color=c=0x2563EB:s=360x640:r=24:d=6',
    '-vf', $vfA, '-an') + $videoCommon + @($a))
Invoke-FixtureFfmpeg ($base + @('-f', 'lavfi', '-i', 'color=c=0xF97316:s=360x640:r=24:d=4',
    '-vf', $vfB, '-an') + $videoCommon + @($b))
Invoke-FixtureFfmpeg ($base + @('-f', 'lavfi', '-i', 'color=c=0x16A085:s=360x640:r=24:d=6',
    '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=48000:duration=6',
    '-vf', $vfC, '-c:a', 'aac', '-b:a', '64k') + $videoCommon + @($c))

$vfPng = "drawbox=x=48:y=56:w=544:h=288:color=white@0.28:t=fill,drawtext=fontfile='$fontFile':text='PNG FIXTURE':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=180"
$vfJpg = "drawbox=x=48:y=56:w=544:h=288:color=white@0.25:t=fill,drawtext=fontfile='$fontFile':text='JPG FIXTURE':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=180"
Invoke-FixtureFfmpeg ($base + @('-f', 'lavfi', '-i', 'color=c=0x22C55E:s=640x400:d=1',
    '-vf', $vfPng, '-frames:v', '1', $png))
Invoke-FixtureFfmpeg ($base + @('-f', 'lavfi', '-i', 'color=c=0xA855F7:s=640x400:d=1',
    '-vf', $vfJpg, '-frames:v', '1', '-q:v', '3', $jpg))
Invoke-FixtureFfmpeg ($base + @('-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=8',
    '-c:a', 'libmp3lame', '-q:a', '7', $mp3))
$pulseExpression = "aevalsrc=0.35*sin(2*PI*880*t)*(between(t\,0.5\,0.7)+between(t\,2.5\,2.7)+between(t\,5.0\,5.2)):s=48000:d=6"
Invoke-FixtureFfmpeg ($base + @('-f', 'lavfi', '-i', $pulseExpression,
    '-c:a', 'pcm_s16le', $wav))

$invalid = Join-Path $FixtureDirectory '08_INVALID_corrupt_mp4.mp4'
[System.IO.File]::WriteAllText($invalid, 'This is intentionally not an MP4 media stream.', [System.Text.UTF8Encoding]::new($false))

$manifest = Join-Path $FixtureDirectory 'FIXTURE_MANIFEST.csv'
$rows = @(
    [pscustomobject]@{ File='01_VIDEO_A_6s_blue.mp4'; Type='video'; DurationSeconds=6; Expected='H.264, no audio, blue frame with VIDEO A label' },
    [pscustomobject]@{ File='02_VIDEO_B_4s_orange.mp4'; Type='video'; DurationSeconds=4; Expected='H.264, no audio, orange frame with VIDEO B label' },
    [pscustomobject]@{ File='03_VIDEO_C_6s_with_audio.mp4'; Type='video'; DurationSeconds=6; Expected='H.264 + AAC 660 Hz tone, teal frame with VIDEO C + AUDIO label' },
    [pscustomobject]@{ File='04_IMAGE_PNG_green.png'; Type='image'; DurationSeconds=''; Expected='640x400 PNG, green frame with PNG FIXTURE label' },
    [pscustomobject]@{ File='05_IMAGE_JPG_purple.jpg'; Type='image'; DurationSeconds=''; Expected='640x400 JPEG, purple frame with JPG FIXTURE label' },
    [pscustomobject]@{ File='06_AUDIO_MP3_440Hz_8s.mp3'; Type='audio'; DurationSeconds=8; Expected='MP3, continuous 440 Hz tone' },
    [pscustomobject]@{ File='07_AUDIO_WAV_markers_0p5_2p5_5s.wav'; Type='audio'; DurationSeconds=6; Expected='WAV 48 kHz mono, 880 Hz pulses at 0.5-0.7, 2.5-2.7, and 5.0-5.2 seconds' },
    [pscustomobject]@{ File='08_INVALID_corrupt_mp4.mp4'; Type='invalid'; DurationSeconds=''; Expected='Intentionally invalid MP4 bytes; should fail import/probe or be rejected when dragged from Explorer' }
)
$rows | Export-Csv -LiteralPath $manifest -NoTypeInformation -Encoding UTF8
Get-ChildItem -LiteralPath $FixtureDirectory -File | Select-Object Name,Length
Write-Output "Fixture manifest: $manifest"
