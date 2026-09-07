# 商品参考资料读取

本规范定义商品资料的读取顺序、用户身份、附件获取和 NAS 回退条件。数据源配置位于 [reference-data-sources.json](../assets/configs/reference-data-sources.json)。

## 读取顺序

1. 从原始数据包根目录解析 KQ 货号。
2. 使用飞书用户身份查询 `产品资料-款-对外`，取得设计编码、货号、品名和附件名称。
3. 使用同一货号查询 `产品资料-码-对外`，取得颜色规格、尺码、成分、执行标准、安全类别和产品分类。
4. 使用设计编码查询 `产品中心信息表spu维度-款` 的真实附件字段，取得商品图片、洗唛、合格证和检测报告的附件令牌。
5. 多维表中的有效字段直接作为当前款依据，NAS 中的同类字段无需读取。
6. 多维表记录不存在，或目标字段为 `null`、空字符串、`/` 时，只针对缺失字段读取对应 NAS。
7. Logo 标准始终从静物拍摄 NAS 获取。

多维表无法访问、用户身份未登录或用户没有资源权限属于依赖失败，不属于字段缺失。先恢复用户授权或资源权限，再继续审核，不使用 NAS 绕过多维表访问失败。

## 用户身份与权限

- 所有多维表命令显式使用 `--as user`。
- 使用者必须完成 `lark-cli` 用户授权，并具备目标 Base 的只读权限。
- 权限范围必须覆盖两个对外表以及附件来源表 `产品中心信息表spu维度-款`。
- 用户身份缺少 scope 时，按 `lark-shared` 的用户授权流程补充最小权限；资源 ACL 不足时，由 Base 所有者为当前用户或质检人员群配置只读权限。
- Skill 和配置文件不保存用户令牌、应用密钥或其他凭证。

## 标准命令

在 Skill 的 `scripts` 目录运行：

```powershell
uv run python .\fetch_base_reference_data.py "<KQ货号>" --output-dir ".\work\<任务标识>\reference-data" --download-attachments
```

脚本执行以下检查：

- 验证 `lark-cli` 用户身份可用。
- 按 KQ 货号精确查询款表和码表。
- 校验查询结果只能对应一个设计编码。
- 读取来源表中的真实附件字段并按资料类型下载。
- 生成 `base-reference-data.json`，记录原始记录、字段缺失、附件清单、下载路径和 NAS 回退要求。

脚本返回非零退出码时，多维表资料未可靠取得，禁止将依赖商品资料的专项判为通过。

## 字段级回退

`base-reference-data.json` 中的 `nas_fallback_required` 决定需要读取的 NAS：

- `product_information=true`：读取产品信息 NAS，只补充 `missing_fields` 列出的业务字段。
- `test_reports=true`：读取检测报告 NAS，匹配当前货号和商品身份。
- `logo_reference=true`：读取静物拍摄 NAS，取得当前款 Logo 参考素材。

从 NAS 补充资料时记录完整路径、文件名、工作表或页码。多维表已有有效值的字段不与 NAS 重复比对。

访问 NAS 后填写 `base-reference-data.json` 中对应的 `nas_resolution`：

- 找到当前款资料：`status=matched`，并在 `matched_paths` 列出完整路径。
- NAS 可访问但没有匹配资料：`status=not_found`，在 `notes` 说明检索范围。
- NAS 无法访问：`status=unavailable`，在 `notes` 说明网络、凭据、权限或目录错误。
- `required=false` 的字段保持 `status=not_required`。

`pending` 表示回退流程尚未完成，不能生成最终报告。

## 审核记录

每款记录以下信息：

- 多维表访问状态和用户身份状态。
- 款表、码表和附件来源表的匹配记录数。
- 设计编码和 KQ 货号匹配结果。
- 每个业务字段的数据来源：`base` 或 `nas_fallback`。
- 多维表缺失字段及对应 NAS 补充结果。
- Logo NAS 的匹配状态。
- 附件名称、附件类型、文件大小、下载路径和审查结果。
