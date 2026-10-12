# img2save.py —— 图片转沙盘(.cps)

把任意图片变成 The Powder Toy(粉末玩具)能直接打开的沙盘文件 `.cps`:每个像素
对应游戏里的一个粒子。

```bash
python3 tools/img2save.py photo.png                   # 生成 photo.cps
```

生成的 `.cps` 可以直接**拖进游戏窗口**, 也可以放进游戏的 `saves` 目录里打开。
打开后画面占在画布左上角, 尺寸就是图片尺寸(默认不超过游戏画布 612 x 384)。

## 依赖

只用到 Python 标准库, 什么都不用装。

* 装了 [Pillow](https://pypi.org/project/Pillow/)(`pip install Pillow`)时,
  jpg / webp / bmp / gif / tiff …… 什么格式都能读。
* 没装 Pillow 时, 脚本会用自带的纯 Python 解码器, **但只能读 PNG**
  (灰度、RGB、RGBA、索引色、8/16 位都能读, 不支持隔行扫描的 PNG)。

## 两种着色方式

### 1. `-m deco`(默认):装饰色, 和原图几乎一模一样

每个像素放一个元素粒子(默认 `DMND` 钻石, 静态、不会动), 再给它加上"装饰色"
(dcolour)。装饰色的 alpha 写 255, 游戏里会**完全替换**元素本来的颜色, 所以画面
和原图是逐像素一致的。

```bash
python3 tools/img2save.py photo.jpg -e WOOD          # 换成木头的"材质"
python3 tools/img2save.py photo.jpg -e INSL          # 换成绝缘体(隔热)
```

> 小提示:如果你在游戏里把"装饰"设置成了"隐藏装饰色"(反标题党模式), 装饰色会被
> 忽略, 整张图会变成所选元素的本色。

### 2. `-m palette`:只用真实元素自己的颜色

不做任何染色, 把每个像素换成颜色最接近的元素。这样沙盘里的东西都是"真"的:
水会流、火会烧、植物会长, 但颜色只能是元素自带的那些, 因此建议开抖动:

```bash
python3 tools/img2save.py photo.jpg -m palette --dither floyd
python3 tools/img2save.py photo.jpg -m palette --palette solid      # 只用静态固体, 画面不会塌
python3 tools/img2save.py photo.jpg -m palette --palette all        # 用游戏里所有元素
python3 tools/img2save.py photo.jpg -m palette --palette WATR,LAVA,GOLD,DMND
```

内置调色板:

| 名字 | 说明 |
| --- | --- |
| `default` | 39 种颜色分得比较开的元素(可能有会动/会烧的) |
| `solid` | 28 种静态固体, 打开后画面不会自己动 |
| `all` | 脚本能安全用于画像的全部元素(从源码里现读并排除人物、传送门等特殊元素) |

用 `--list-elements` 可以查看所有元素(编号、颜色、名字)。

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `-o FILE` | 输出文件名, 默认 `图片名.cps` |
| `-W N` / `-H N` | 指定宽度/高度(像素), 只给一个时另一个按比例算; 都会取整到 4 的倍数 |
| `--scale N` | 在自动算出的尺寸上再乘一个系数 |
| `--upscale` | 允许把小图放大(默认只会缩小) |
| `-m deco\|palette` | 着色方式 |
| `-e NAME` | deco 模式用哪种元素当画布(默认 `DMND`) |
| `--palette ...` | palette 模式的调色板 |
| `--dither none\|floyd` | palette 模式的抖动 |
| `--alpha-threshold N` | 透明度低于 N(0-255)的像素留空, 默认 128 |
| `--key-color RRGGBB` | 把某个颜色当成透明(比如去掉白底 `FFFFFF`) |
| `--key-tolerance N` | `--key-color` 的容差, 默认 24 |
| `--temp N` | 粒子温度(开尔文), 默认 295 |
| `--paused` | 存档打开时是暂停的 |
| `--gravity`, `--air` | 重力/空气模式 |
| `--sign 文字` | 在左下角加一行说明(支持中文) |
| `--preview FILE` | 顺便导出一张 PNG 预览图 |
| `--verify` | 写完后按游戏的读档顺序回读存档, 逐格校验 |
| `-q` | 少打印信息 |

## 例子

```bash
# 1) 一张照片, 铺满整个画布(612 x 384)
python3 tools/img2save.py 照片.jpg -W 612 -H 384

# 2) 公司 logo: 去掉白底, 用石头画, 顺便看预览
python3 tools/img2save.py logo.png --key-color FFFFFF -e STNE --preview 预览.png

# 3) 像素画: 不缩放, 原尺寸一比一还原
python3 tools/img2save.py pixelart.png

# 4) 用元素本色拼一张会动的画, 打开时暂停, 加个签名
python3 tools/img2save.py 风景.jpg -m palette --dither floyd --paused --sign "by 我"
```

## 一些细节

* **尺寸**:游戏画布是 612 x 384, 而 PSv 存档里宽高要按 4 像素一格来存, 所以输出
  尺寸会自动取整到 4 的倍数。显式指定超过画布的尺寸时脚本会报错。
* **元素表**:脚本启动时直接从本仓库的源码里读元素编号和颜色
  (`src/simulation/elements/`), 所以和当前这个版本的元素编号永远一致。把脚本单独
  拷到别处用时, 会退回脚本内置的那份元素表。
* **存档格式**:写的是 PSv 格式(version 97, bzip2 压缩), 也就是老版本 `.cps` 的
  格式, 现在这份代码里的 `GameSave::readPSv` 仍然能正常读它(游戏自己现在写的是
  新的 OPS 格式)。
* **文件体积**:一屏 612 x 384 的照片大约几十 KB, 噪点那种极难压缩的图最多 1 MB 上下。
* **缩放算法**:无论是否安装 Pillow, 都用脚本内置的区域平均(box filter)缩小 +
  最近邻放大。缩放是在 sRGB 空间直接平均的, 没有做 gamma 校正。

## 自测

```bash
python3 tools/img2save.py 图片.png --verify --preview 预览.png
```

`--verify` 会按 `src/client/GameSave.cpp` 里 `readPSv()` 的读取顺序把刚写出来的
存档重新解开, 和内存里的粒子逐格对比(元素编号 + 装饰色), 并且要求解析结束后字节
数刚好用完。
