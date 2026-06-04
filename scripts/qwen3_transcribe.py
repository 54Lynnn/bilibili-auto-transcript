#!/usr/bin/env python3
"""
Qwen3-ASR 转录辅助脚本 v1.1（保留/可选）

注意：当前 bilibili_transcript.sh v5.0 默认使用 Whisper。
该脚本保留作为 Qwen3-ASR 的可选替代，如需使用需手动修改 shell 脚本调用路径。

自动检测设备 (CUDA/ROCm/MPS/CPU)，自动选择模型 (1.7B/0.6B)

输出格式（写入 --output-file）：
  第一行：转录来源字符串（如 "Qwen3-ASR-1.7B（GPU加速）"）
  第二行起：完整转录文本
"""

import argparse
import os
import sys


def detect_device():
    """检测最佳可用设备，返回 device_map 字符串"""
    try:
        import torch
    except ImportError:
        return "cpu"

    # NVIDIA CUDA / AMD ROCm
    if torch.cuda.is_available():
        return "cuda"

    # Apple Metal (MPS)
    if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        return "mps"

    return "cpu"


def device_label(device_map):
    return {"cuda": "CUDA", "mps": "Apple MPS", "cpu": "CPU"}.get(device_map, device_map.upper())


def select_model(device_map):
    """根据设备自动选择模型版本"""
    if device_map == "cpu":
        return "Qwen/Qwen3-ASR-0.6B", "0.6B"
    return "Qwen/Qwen3-ASR-1.7B", "1.7B"


def main():
    parser = argparse.ArgumentParser(description="Qwen3-ASR 语音转录")
    parser.add_argument("--audio", required=True, help="音频文件路径")
    parser.add_argument("--output-file", required=True, help="输出文件路径（第一行=来源，后续=文本）")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "mps"],
                        help="设备选择 (默认: auto 自动检测)")
    args = parser.parse_args()

    if not os.path.exists(args.audio):
        print("错误: 音频文件不存在", file=sys.stderr)
        sys.exit(1)

    # === 设备检测 ===
    device_map = detect_device()
    if args.device != "auto":
        device_map = args.device

    # === 模型选择 ===
    model_name, model_short = select_model(device_map)

    print(f"🎤 使用 Qwen3-ASR-{model_short}", file=sys.stderr)
    print(f"   ⚙️  设备: {device_label(device_map)}", file=sys.stderr)
    print(f"   📦 模型: {model_name}", file=sys.stderr)
    print(f"   ⏳ 加载模型中（首次需下载权重 {model_short} ~{2 if model_short == '0.6B' else 5}GB）...", file=sys.stderr)

    try:
        from qwen_asr import Qwen3ASRModel

        model = Qwen3ASRModel.from_pretrained(
            model_name,
            device_map=device_map,
            torch_dtype="auto",
            max_new_tokens=2048,
        )

        print(f"   ✅ 模型加载完成", file=sys.stderr)
        print(f"   🎤 正在转录...", file=sys.stderr)

        results = model.transcribe(args.audio)
        transcript = results[0].text if results else ""

        if not transcript or transcript.strip() == "":
            print("错误: 转录结果为空", file=sys.stderr)
            sys.exit(1)

        transcript = transcript.strip()

        # === 构造来源描述 ===
        source = f"Qwen3-ASR-{model_short}"
        lbl = device_label(device_map)
        if lbl != "CPU":
            source += f"（{lbl}加速）"

        # === 写入输出文件 ===
        # 第一行: 来源字符串
        # 第二行起: 转录文本
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(source + "\n")
            f.write(transcript + "\n")

        print(f"   ✅ 转录完成", file=sys.stderr)
        print(f"   📄 来源: {source}", file=sys.stderr)

    except ImportError:
        print("错误: 请先在虚拟环境中安装 qwen-asr: .venv/bin/pip install qwen-asr", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: 转录失败 - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
