#!/usr/bin/env python3
"""隔离推理进程入口（运行于 .venv-photo，参数列表启动，不拼 shell）。

子命令：
- infer：DA2-Small 相对深度真实推理（transformers 实现，仅本地权重），
  输出 depth_raw.npy（float32，值大=离相机近）+ metadata.json。
- download：显式下载模型到 models/<provider>/<model>/<revision>/ 并写 hash 清单
  （仅本子命令联网；权重总量超过 --limit-bytes 直接中止）。
- verify：按清单重算 SHA-256。

深度语义记录为 relative_larger_nearer；蒙版不改变推理输入（默认用原照片，
保留场景上下文），仅用于有效域与后续归一化。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
import time
from pathlib import Path

DEFAULT_REPO = "depth-anything/Depth-Anything-V2-Small-hf"
DEFAULT_MODEL_ID = "depth-anything-v2-small-hf"
DEFAULT_LIMIT_BYTES = 1_000_000_000  # P1 权重预算上限（十进制 1GB，不含运行环境）
ALLOW_PATTERNS = ("*.json", "*.txt", "*.safetensors")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cmd_infer(args: argparse.Namespace) -> int:
    import numpy as np
    import torch
    import transformers
    from PIL import Image
    from transformers import AutoImageProcessor, DepthAnythingForDepthEstimation

    started = time.time()
    image = Image.open(args.image).convert("RGB")
    with Image.open(args.mask) as mask_image:
        mask_size = mask_image.size
    processor = AutoImageProcessor.from_pretrained(args.model, local_files_only=True)
    model = DepthAnythingForDepthEstimation.from_pretrained(args.model, local_files_only=True)

    # 计算设备与展示标签分开：manifest 记录 device（含回退标注），
    # 传给 torch 的始终是合法设备字符串（"cpu"/"mps"）。
    requested = args.device
    mps_available = torch.backends.mps.is_available()
    if requested == "mps" and not mps_available:
        print("--device mps 但本机 MPS 不可用；拒绝静默回退，请改用 auto 或 cpu", file=sys.stderr)
        return 3
    device = "mps" if requested in ("auto", "mps") and mps_available else "cpu"
    device_label = device

    def forward(dev: str):
        local = model.to(dev)
        local.eval()
        inputs = processor(images=image, return_tensors="pt").to(dev)
        with torch.no_grad():
            return local(**inputs)

    try:
        outputs = forward(device)
    except RuntimeError:
        if device == "cpu":
            raise  # CPU 路径失败即真实错误，不做无意义重试
        print("MPS 推理失败，回退 CPU 重跑（manifest 将标注设备回退）", file=sys.stderr)
        outputs = forward("cpu")
        device, device_label = "cpu", "cpu（MPS 不可用回退）"

    predicted = outputs.predicted_depth.float()
    if predicted.ndim == 2:
        predicted = predicted.unsqueeze(0).unsqueeze(0)
    elif predicted.ndim == 3:
        predicted = predicted.unsqueeze(1)
    # 与官方 pipeline 一致的后处理：双三次插值回原图尺寸
    predicted = torch.nn.functional.interpolate(
        predicted, size=image.size[::-1], mode="bicubic", align_corners=False
    ).squeeze()
    depth = predicted.cpu().numpy().astype(np.float32)
    args.out.mkdir(parents=True, exist_ok=True)
    np.save(args.out / "depth_raw.npy", depth)
    manifest = json.loads((Path(args.model) / "manifest.json").read_text(encoding="utf-8"))
    metadata = {
        "model": {
            "model_id": manifest.get("model_id", DEFAULT_MODEL_ID),
            "repo_id": manifest.get("repo_id", DEFAULT_REPO),
            "revision": manifest.get("revision"),
            "license": manifest.get("license"),
            "manifest_sha256": _sha256(Path(args.model) / "manifest.json"),
        },
        "implementation": f"transformers {transformers.__version__}",
        "torch": torch.__version__,
        "device": device_label,
        "device_requested": requested,
        "elapsed_s": round(time.time() - started, 3),
        "semantics": "relative_larger_nearer",
        "input_size": list(image.size),
        "mask_size": list(mask_size),
        "output_shape": list(depth.shape),
        "mask_used_for_inference": False,
        "postprocess": "bicubic interpolate to input size（与 transformers 官方 pipeline 一致）",
    }
    (args.out / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "device": device, "shape": list(depth.shape)}))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    import requests
    from huggingface_hub import HfApi, snapshot_download

    # 官方源直连在部分网络下会被中断；hf-mirror.com 为社区镜像。
    # 无论来源，文件一致性由本地 SHA-256 清单校验兜底；endpoint 记入 manifest 备查。
    endpoints = (
        [args.endpoint] if args.endpoint else ["https://huggingface.co", "https://hf-mirror.com"]
    )
    info = None
    used_endpoint = endpoints[0]
    last_error: Exception | None = None
    for endpoint in endpoints:
        api = HfApi(endpoint=endpoint)
        try:
            try:
                info = api.model_info(args.repo, files_metadata=True, revision=args.revision)
            except requests.exceptions.RequestException:
                # blobs 元数据请求不稳定时降级为普通 model_info（仍带 revision）
                info = api.model_info(args.repo, revision=args.revision)
        except requests.exceptions.RequestException as exc:
            last_error = exc
            print(f"元数据请求失败（{endpoint}）：{exc}", file=sys.stderr)
            continue
        siblings = info.siblings or []
        names = sorted(s.rfilename for s in siblings)
        # 截断/异常响应会缺失权重文件：视为该源不可用，换下一个
        if not any(name.endswith(".safetensors") for name in names):
            print(
                f"源 {endpoint} 返回的文件列表缺少权重（共 {len(names)} 项：{names}），换源重试",
                file=sys.stderr,
            )
            info = None
            continue
        used_endpoint = endpoint
        break
    if info is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"仓库 {args.repo} 在所有源上均未取得有效文件列表")
    siblings = info.siblings or []
    # 尺寸元数据在部分 hub 版本/xet 仓库上会缺失：文件名必有，尺寸可后验
    sizes = {s.rfilename: s.size for s in siblings if s.size}
    keep = sorted(
        s.rfilename
        for s in siblings
        if any(fnmatch.fnmatch(s.rfilename, pattern) for pattern in ALLOW_PATTERNS)
    )
    if not keep:
        print(f"仓库 {args.repo} 中没有匹配 {ALLOW_PATTERNS} 的文件", file=sys.stderr)
        return 1
    known_total = sum(sizes.get(name, 0) for name in keep)
    missing = [name for name in keep if name not in sizes]
    print(f"计划下载（revision {info.sha[:12]}，许可 {args.license}）：")
    for name in keep:
        size_text = f"{sizes[name] / 1e6:9.2f} MB" if name in sizes else "  尺寸未知"
        print(f"  {size_text}  {name}")
    print(
        f"已知合计 {known_total / 1e6:.2f} MB"
        f"（{len(missing)} 个文件尺寸未知，下载后按实际核对；上限 {args.limit_bytes / 1e6:.0f} MB）"
    )
    if known_total > args.limit_bytes:
        print("超过权重预算，中止；请人工确认后再调整上限", file=sys.stderr)
        return 2
    revision_root = args.out / str(info.sha)
    if revision_root.exists() and (revision_root / "manifest.json").is_file():
        print(f"已存在：{revision_root}")
        return 0
    download_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            snapshot_download(
                repo_id=args.repo,
                revision=info.sha,
                local_dir=revision_root,
                allow_patterns=keep,
                cache_dir=str(args.cache),
                endpoint=used_endpoint,
            )
            download_error = None
            break
        except requests.exceptions.RequestException as exc:  # 网络中断：断点续传重试
            download_error = exc
            print(f"下载中断（第 {attempt} 次）：{exc}；重试…", file=sys.stderr)
    if download_error is not None:
        raise download_error
    revision_root.mkdir(parents=True, exist_ok=True)
    files = {
        path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in sorted(revision_root.iterdir())
        if path.is_file() and path.name != "manifest.json"
    }
    total = sum(entry["bytes"] for entry in files.values())
    if total > args.limit_bytes:
        print(f"实际下载 {total / 1e6:.2f} MB 超过预算，删除并中止", file=sys.stderr)
        import shutil

        shutil.rmtree(revision_root)
        return 2
    manifest = {
        "schema_version": 1,
        "provider": "hf",
        "model_id": args.model_id,
        "repo_id": args.repo,
        "revision": info.sha,
        "endpoint": used_endpoint,
        "license": args.license,
        "license_source": "命令行声明，以仓库/模型卡为准（须人工核对）",
        "implementation": "transformers（版本见 photo-inference.lock）",
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "size_total_bytes": int(total),
        "files": files,
    }
    (revision_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 记录当前选中版本：locate() 优先读取，不靠 revision 目录名（提交 hash）排序猜最新
    (args.out / "selected.json").write_text(
        json.dumps(
            {
                "revision": info.sha,
                "selected_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "note": "download 时写入；ModelRegistry.locate 优先使用",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"完成：{revision_root}（实际 {total / 1e6:.2f} MB）")
    return cmd_verify(argparse.Namespace(model=str(revision_root)))


def cmd_verify(args: argparse.Namespace) -> int:
    model = Path(args.model)
    manifest_path = model / "manifest.json"
    if not manifest_path.is_file():
        print(f"清单缺失：{manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failed = False
    for name, expected in manifest.get("files", {}).items():
        path = model / name
        if not path.is_file():
            print(f"缺失：{name}", file=sys.stderr)
            failed = True
            continue
        actual = _sha256(path)
        state = "OK" if actual == expected.get("sha256") else "HASH 不匹配"
        if actual != expected.get("sha256"):
            failed = True
        print(f"{state}：{name}")
    return 1 if failed else 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = result.add_subparsers(dest="command", required=True)
    infer = sub.add_parser("infer")
    infer.add_argument("--image", type=Path, required=True)
    infer.add_argument("--mask", type=Path, required=True)
    infer.add_argument("--model", type=Path, required=True)
    infer.add_argument("--out", type=Path, required=True)
    infer.add_argument(
        "--device",
        choices=["auto", "cpu", "mps"],
        default="auto",
        help="auto=优先 MPS 失败回退 CPU；cpu 可在 MPS 机器上复跑 CPU 基线；mps 不可用则直接报错",
    )
    download = sub.add_parser("download")
    download.add_argument("--repo", default=DEFAULT_REPO)
    download.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    download.add_argument("--revision", default=None)
    download.add_argument(
        "--endpoint",
        default=None,
        help="强制指定下载源（默认依次尝试 huggingface.co 与 hf-mirror.com）",
    )
    download.add_argument("--out", type=Path, required=True)
    download.add_argument("--cache", type=Path, required=True)
    download.add_argument("--license", default="Apache-2.0")
    download.add_argument("--limit-bytes", type=int, default=DEFAULT_LIMIT_BYTES)
    verify = sub.add_parser("verify")
    verify.add_argument("--model", type=Path, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "infer":
        return cmd_infer(args)
    if args.command == "download":
        return cmd_download(args)
    return cmd_verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
