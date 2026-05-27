# image_factory

Prompt 文档工厂，面向外部生图平台（DALL-E / Midjourney / Stable Diffusion / 即梦）。从自然语言主题生成 Markdown + 自包含 HTML prompt 文档，支持参考图匹配、资料召回和批量 API 出图。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 离线示例

运行示例 prompt 文档生成（使用最小示例数据集）：

```bash
python3 scripts/make_prompt_doc.py \
  --theme "示例角色在阳光明媚的花园中阅读" \
  --character "示例角色" \
  --specs-dir examples/minimal/specs \
  --out examples/minimal/prompts/docs/generated_sample.md
```

注意：示例数据集包含一个示例参考图和基础风格指南，可用于验证工具的基本功能。

## Prompt 文档校验

验证 prompt 文档是否有配对的 embedded HTML：

```bash
python3 scripts/check_prompt_docs.py --docs-dir examples/minimal/prompts/docs
```

## 参考图资源校验

验证参考图文件是否存在且可访问：

```bash
python3 scripts/check_references.py --specs-dir examples/minimal/specs
```

## API 安全模型

API 调用需要双重安全开关：

1. 环境变量 `IMAGE_FACTORY_API_ENABLED=1`
2. CLI 参数 `--allow-api`

两者缺一不可，默认状态下 API 调用会被阻止。

## 环境变量配置

复制 `.env.example` 为 `.env` 并填入你的 API 密钥：

```bash
cp .env.example .env
# 编辑 .env 文件，填入实际的 API 密钥
```

## 数据说明

本公开仓库仅包含示例数据，用于演示工具功能。示例数据包括：

- `examples/minimal/specs/` - 最小化的风格指南和参考图索引
- `examples/minimal/assets/references/` - 示例参考图
- `examples/minimal/prompts/docs/` - 示例 prompt 文档

实际使用时，请根据需要创建自己的 specs 和参考图资源。

## 项目结构

```
scripts/                  - 生成、校验、API 调用脚本
src/image_factory/        - Python 核心包
examples/minimal/         - 最小示例数据集
docs/                     - 项目文档
```

## 安全说明

- API key 只从环境变量或 `.env` 读取
- `.env` 永不入 git
- 双重安全开关：环境变量 + CLI 参数缺一不可
- 触网脚本默认中止，不误调用外部 API

## 许可证

MIT License
