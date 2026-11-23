"""Ядро: розділення двох спікерів по каналах стерео WAV (pyannote.audio).

Модуль не взаємодіє з користувачем напряму (немає input/print):
прогрес і повідомлення передаються через колбек on_status(text, log=True).
"""
import wave
import os
from pathlib import Path

import torch
from dotenv import load_dotenv
from pyannote.audio import Audio, Pipeline

load_dotenv(Path(__file__).with_name(".env"))

MODEL_ID = "pyannote/speaker-diarization-3.1"
NUM_SPEAKERS = 2

_pipeline = None  # кеш: модель вантажиться один раз за сеанс


def _noop(*args, **kwargs):
    pass


def get_device_info() -> str:
    """Короткий опис пристрою, який буде використано в режимі «Авто»."""
    if torch.cuda.is_available():
        return f"GPU ({torch.cuda.get_device_name(0)})"
    return "CPU"


def unique_path(path) -> Path:
    """Якщо файл уже існує, додає числовий суфікс, щоб нічого не перезаписати."""
    path = Path(path)
    if not path.exists():
        return path
    for i in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Не вдалося підібрати вільне ім'я для {path}")


def _get_pipeline(on_status):
    global _pipeline
    if _pipeline is None:
        token = os.getenv("HF_TOKEN")
        if not token:
            raise RuntimeError(
                "HF_TOKEN відсутній. Скопіюйте .env.example у .env і вставте "
                "свій токен Hugging Face (read)."
            )
        on_status("Завантаження моделі (при першому запуску може тривати довго)…")
        _pipeline = Pipeline.from_pretrained(MODEL_ID, token=token)
        if _pipeline is None:
            raise RuntimeError(
                "Не вдалося завантажити модель. Перевірте токен і те, що на "
                "Hugging Face прийняті умови доступу до моделей pyannote."
            )
    return _pipeline


def _run(pipeline, waveform, sample_rate, uri, device, on_status):
    pipeline.to(torch.device(device))
    audio = {"waveform": waveform, "sample_rate": sample_rate, "uri": uri}
    state = {"step": None}

    def hook(step_name, step_artifact, file=None, total=None, completed=None):
        new_step = step_name != state["step"]
        state["step"] = step_name
        if total and completed is not None:
            text = f"Діаризація: {step_name} ({completed}/{total})"
        else:
            text = f"Діаризація: {step_name}"
        on_status(text, log=new_step)

    return pipeline(audio, num_speakers=NUM_SPEAKERS, hook=hook)


def diarize_to_stereo(input_wav, output_path, device_pref="auto", on_status=_noop) -> dict:
    """Розділяє двох спікерів по каналах і зберігає стерео WAV.

    device_pref: "auto" (GPU, якщо доступний) або "cpu".
    Повертає {"path", "speakers", "device"}.
    """
    pipeline = _get_pipeline(on_status)

    on_status("Читання аудіо…")
    waveform, sample_rate = Audio(mono="downmix")(str(input_wav))
    waveform = waveform.cpu()
    uri = Path(input_wav).stem

    device = "cuda" if (device_pref != "cpu" and torch.cuda.is_available()) else "cpu"
    on_status(f"Діаризація на {'GPU' if device == 'cuda' else 'CPU'}…")

    try:
        diarization = _run(pipeline, waveform, sample_rate, uri, device, on_status)
    except torch.cuda.OutOfMemoryError:
        if device != "cuda":
            raise
        torch.cuda.empty_cache()
        on_status("Не вистачило пам'яті GPU, повторюю на CPU…")
        device = "cpu"
        diarization = _run(pipeline, waveform, sample_rate, uri, device, on_status)

    annotation = diarization.speaker_diarization
    speakers = sorted(
        {label for _, _, label in annotation.itertracks(yield_label=True)}
    )
    if len(speakers) != NUM_SPEAKERS:
        raise RuntimeError(
            f"Очікувалося {NUM_SPEAKERS} спікери, а виявлено {len(speakers)}: {speakers}"
        )

    on_status("Формування стерео…")
    mono = waveform[0]
    total = mono.shape[0]
    stereo = torch.zeros((2, total), dtype=mono.dtype)
    for channel, speaker in enumerate(speakers):
        for segment, _, label in annotation.itertracks(yield_label=True):
            if label == speaker:
                start = max(0, round(segment.start * sample_rate))
                end = min(total, round(segment.end * sample_rate))
                stereo[channel, start:end] = mono[start:end]

    pcm = (
        stereo.clamp(-1, 1)
        .mul(32767)
        .round()
        .to(torch.int16)
        .transpose(0, 1)
        .contiguous()
        .numpy()
        .tobytes()
    )

    on_status("Збереження файлу…")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(sample_rate)  # частота дискретизації оригіналу
        out.writeframes(pcm)

    return {"path": output_path, "speakers": speakers, "device": device}
