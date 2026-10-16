# Intent 参数绑定与候选值设计

## 目标

基础 Slot 沿用原有的 `string` / `enum` 类型：文本 Slot 由模型提取，枚举 Slot 由程序按 canonical、display 和 aliases 匹配。`number` 只是示例中的普通文本 Slot 名称，不是系统类型。Intent 参数定义该值在具体业务中的字段名、是否必填、默认值以及业务转换和限制。

整个识别过程只调用一次 LLM：程序先从用户原文提取枚举 Slot 候选，再把候选、Intent 定义和用户原文放入同一次 Prompt；模型识别 Intent、提取文本 Slot，并将取值绑定到业务字段。

## 配置模型

```json
{
  "name": "volume_up",
  "required_slots": [
    {
      "slot_name": "number",
      "field_name": "volume",
      "field_zh": "音量值",
      "required": true,
      "default_value": null,
      "note": "只提取正数；5% 统一转换为 5"
    }
  ]
}
```

- `slot_name` 引用一个已启用的基础 Slot。
- `field_name` 与 `field_zh` 是当前 Intent 中的业务字段映射；未填写的字段分别回退到基础 Slot 的 `name` 和 `zh`。
- `required` 省略时默认为 `false`；仅显式设为 `true` 的参数在缺失且无默认值时生成追问。
- `note` 是属于 Intent 参数的自由文本备注，可描述提取限制、值转换或其他业务要求；同一个基础 Slot 在不同 Intent 中可以配置不同备注。
- 同一个 Intent 可以多次引用同一个基础 Slot，只要求最终业务英文字段不重复。

系统不为备注规定选项、语法或 Slot 类型限制；备注会以原文进入该 Intent 的参数说明，由同一次 LLM 调用在绑定字段时执行。

## 单次调用数据流

```text
用户原文
   │
   ├── 程序按枚举 Slot 的词典提取候选
   │
   └── 一次 LLM 调用
          ├── 识别 Route / Intent
          ├── 从原文提取文本 Slot
          └── 根据原文语义，把取值绑定到所选 Intent 的业务字段
                    │
                    ▼
             程序处理默认值和必填校验
```

枚举候选值只按基础 Slot 在 Prompt 中出现一次，不会复制到使用该 Slot 的每个 Intent 参数下。Intent 模块只保留紧凑映射，例如：

```text
- volume_up：调大音量
  参数：volume/音量值<-number[必填;备注=只提取正数；5% 统一转换为 5]
- brightness_up：调高屏幕亮度
  参数：brightness/亮度值<-number[必填;备注=只提取正数；5% 统一转换为 5]

## 文本 Slot
- number（数值）：由模型从用户原文提取
```

对于“音量提高5，亮度提高10”，模型在同一次返回中把 `5` 绑定为 `volume`，把 `10` 绑定为 `brightness`。

## Slot 提取

- `string` Slot 由 LLM 从原文开放提取；Enum / Alias 页面中的参考示例只用于提示，不限制输出。
- `enum` Slot 由程序使用 canonical、display、aliases 提取候选，命中后统一为 canonical。
- 完整枚举词典不进入最终 Prompt；Prompt 只包含本次请求实际命中的枚举候选值。

## 必填、默认值与校验

- 必填字段已绑定：采用提取值，并遵守参数备注中的要求。
- 必填字段缺失且有默认值：程序补入默认值，并记录 `REQUIRED_SLOT_DEFAULT_APPLIED`。
- 必填字段缺失且无默认值：程序生成澄清，并记录 `REQUIRED_SLOT_MISSING`。
- 可选字段缺失：不追问。
- 备注中的业务要求由 LLM 在候选值绑定时执行；程序只做基础 Slot 类型校验和必填/default 处理。
- V1 以 Top-1 Intent 为准；V2 对每个 action 的 Intent 和其原文范围分别处理候选。
- 训练 Intent 与其他 Intent 使用相同的参数提取、默认值和缺参澄清规则。计划中的结果匹配验证对训练业务只比较一级 Route；该验证功能尚未实现。

默认值没有原文位置，输出使用 `start=0`、`end=0`、`confidence=1`。候选值和转换后的最终值均按字符串输出；程序内部保留原始候选文本用于原文位置校验。
