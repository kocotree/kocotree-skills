# 17 项历史错误示例

本索引配合 [质量检查覆盖清单](quality-check-coverage.md) 使用。图片来自《数据包前期错误清单汇总_已删减.xlsx》，用于帮助识别问题形态，不替代当前款原图、产品信息、Logo 标准和检测报告。

执行对应检查项时打开相关示例图，先理解红框或对照关系，再按当前规则和当前款证据判断。示例中没有红框时，结合本索引说明定位差异。

## 1. 数据包结构与命名

- 示例：[不同数据包使用不同目录结构](../assets/historical-error-examples/01-数据包目录格式.jpeg)
- 关注根目录、六类一级目录、尺寸子目录、素材归属和文件命名是否符合当前输入包规范。
- 使用 `scripts/validate_source_pack_naming.py` 输出结构化结果，并人工确认素材实际类型。

## 2. SKU 品名或商品身份

- 示例：[色名与文件名、画面标注不一致](../assets/historical-error-examples/02-01-SKU品名错乱.jpeg)
- 示例：[同组 SKU 使用具体颜色名称](../assets/historical-error-examples/02-02-SKU品名错乱.png)
- 核对文件名、画面色名、商品颜色、规格和实际商品身份；颜色名称以当前款产品信息为准。

## 3. 详情页切片高度

- 示例：[790×1506 与 790×1731 的实际高度对照](../assets/historical-error-examples/03-详情页高度.jpeg)
- 单张详情页切片高度小于等于 1600 像素时通过，超过 1600 像素时列为需修改。
- 读取图片真实像素，不根据缩略图或文件名推测。

## 4. 数字与字体一致性

- 示例：[尺码数据中的数字 `1`](../assets/historical-error-examples/04-01-数字字体.png)
- 示例：[单位区域的字形与字重](../assets/historical-error-examples/04-02-单位字体.png)
- 示例：[步骤编号中的数字 `1`](../assets/historical-error-examples/04-03-步骤字体.png)
- 全详情页逐个检查数字 `1`，与阿里妈妈方圆体 SemiBold 标准字形比较；同时检查同层级文字的字体、字号、字重和基线一致性。

## 5. 主体与画面边缘关系

- 示例：[主图左侧出现窄白边](../assets/historical-error-examples/05-主图边缘.jpeg)
- 放大检查上、右、下、左四边的白边、异常空隙、错位和拼接缝，重点检查连续品牌横条左右端及 1–3 px 非设计性窄边。
- 详情图同时检查图片内部模块之间的白缝、断层和未贴合。
- 文字或主体裁切按有效视觉损失判定；非设计性白边和接缝按实际像素及画面结构判断。

## 6. 文案语义与断句

- 示例：[“洗后”被拆分到两行](../assets/historical-error-examples/06-01-文案断句.jpeg)
- 示例：[“网孔”被拆分后改变阅读顺序](../assets/historical-error-examples/06-02-文案断句.png)
- 结合完整句意检查固定词组、标点、换行和上下行阅读顺序。
- 逐字检查同音或近音字、错漏字和商品语境中的动词搭配；服装使用“穿”，帽子、太阳镜等佩戴类使用“戴”。

## 7. 详情页模块序号

- 示例：[可见模块编号从 04 跳到 06](../assets/historical-error-examples/07-详情模块序号.jpeg)
- 检查画面内可见编号的跳号、倒序、重复和编号内容对应关系。
- 本项检查画面内容，不以详情文件名是否连续代替判断。

## 8. Logo 局部变形

- 示例：[服装背部 Logo 字形变形](../assets/historical-error-examples/08-01-AI-Logo变形.jpeg)
- 示例：[局部 Logo 轮廓和字样变形](../assets/historical-error-examples/08-02-AI-Logo变形.png)
- 与当前款标准 Logo 比对轮廓、字样、比例和组合关系；实拍透视或褶皱需要多图交叉确认。

## 9. Logo 镜像与方向

- 示例：[圆形 Logo 的文字和图形方向异常](../assets/historical-error-examples/09-Logo镜像.jpeg)
- 检查水平镜像、垂直镜像、旋转方向、文字方向和图形朝向。

## 10. Logo 落位

- 示例：[裤装 Logo 的方向与位置关系](../assets/historical-error-examples/10-01-Logo位置.jpeg)
- 示例：[同款裤装 Logo 的正确部位对照](../assets/historical-error-examples/10-02-Logo位置.jpeg)
- 同款多图对照 Logo 所在左右侧、上下位置、商品部位和方向；镜像调整后仍需重新核对落位。

## 11. Logo 适用性

- 示例：[不同裤装上的 Logo 版本与结构对照](../assets/historical-error-examples/11-Logo使用.jpeg)
- 核对品牌、Logo 版本、颜色、组合方式和当前商品是否匹配。

## 12. 尺码表脚注

- 示例：[尺码表脚注区域](../assets/historical-error-examples/12-尺码误差说明.png)
- 原图已有脚注时，检查文字、数值、单位和适用范围。
- 脚注区域为空本身不构成错误，不要求新增固定测量误差说明。

## 13. 尺码字段与单位完整性

- 示例：[身高、体重与试穿数据单位标注](../assets/historical-error-examples/13-尺码单位标注.jpeg)
- 核对身高、体重、胸围、腰围、臀围和试穿尺码的字段、单位与表格结构，确认每个单位能明确对应数据。

## 14. 尺码单位与数据物理量

- 示例：[试穿报告中的身高体重数据与单位](../assets/historical-error-examples/14-01-尺码单位数据.jpeg)
- 示例：[尺码快选中的区间数据与单位](../assets/historical-error-examples/14-02-尺码单位数据.jpeg)
- 根据字段含义和当前款依据判断数据属于厘米、千克或斤，检查表头单位与表内数值物理量是否匹配。

## 15. 品牌时间或年限信息

- 示例：[同一详情页出现 17 年与 10 年](../assets/historical-error-examples/15-品牌年限.jpeg)
- 跨主图、详情页和随包资料核对品牌成立时间、品牌年限及相关宣传；资料不能证明正确口径时标记待补证。

## 16. 材质信息与随包资料

- 示例：[详情页材质比例](../assets/historical-error-examples/16-01-面料信息.png)
- 示例：[水洗唛成分与部位说明](../assets/historical-error-examples/16-02-水洗唛.png)
- 比对产品信息、详情页、水洗唛、合格证和吊牌中的成分名称、比例、部位及“涂层除外”等限定文字。

## 17. 商品与检测资料一致性

- 示例：[检测报告项目与详情页标准编号对照](../assets/historical-error-examples/17-检测报告.png)
- 先确认报告样品、货号和适用范围，再核对项目、方法、标准编号、单位、实测值和结论。
- 宣传内容缺少对应报告或报告范围不足时标记待补证；当前款权威资料直接冲突时列为已确认错误。
