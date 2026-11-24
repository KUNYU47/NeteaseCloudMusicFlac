# NeteaseCloudMusicFlac

根据网易云音乐的**专辑**、**歌单**或**单曲**链接，下载无损 FLAC 歌曲到本地。

> 本程序仅供学习与个人备份之用。音乐版权归原作者与网易云音乐所有，请勿用于传播或商业用途。

## 重要说明（2026 更新）

原版脚本依赖的百度音乐接口（`musicapi.qianqian.com` / `music.baidu.com/data/music/fmlink`）已经
关闭多年，旧版 `main.py` 无法再下载任何歌曲。当前版本直接调用网易云音乐接口：

- 支持专辑、歌单、单曲的网页链接，也支持纯数字 ID；
- 默认只保存无损 FLAC；没有 VIP 时默认不保存，并提示如何登录；
- 支持多线程下载、失败重试、跳过已存在文件，以及 `--dry-run` 预览实际可用音质；
- 日志同时输出到终端和 `download.log`；
- 原始百度接口版本备份为 `main_original_baidu.py`，仅作参考。

本仓库是在原项目基础上的维护分支，原项目及版权归 YongHaoHu 等作者所有。

## 环境要求

- Python 3.8+
- `requests>=2.31.0`
- `tqdm>=4.66.0`

## 安装

```bash
git clone https://github.com/KUNYU47/NeteaseCloudMusicFlac.git
cd NeteaseCloudMusicFlac
pip install -r requirements.txt
```

> 网易云的无损（FLAC / Hi-Res）资源要求账号**已登录且开通 VIP**。游客身份最多只能获取
> 320kbps MP3；此时默认不会保存文件。

## 使用

```bash
# 专辑
python main.py "https://music.163.com/#/album?id=198202188"

# 歌单
python main.py "https://music.163.com/#/playlist?id=145258012"

# 单曲
python main.py "https://music.163.com/song?id=2162756781"

# 也可以只给数字 ID（先按专辑查询，失败后再按歌单查询）
python main.py 198202188
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `-m, --mp3` | 同时允许保存 MP3（没有 VIP 时只能拿到 320kbps MP3） |
| `--cookie "MUSIC_U=..."` | 登录 cookie，用于获取无损 FLAC |
| `--level {standard,higher,exhigh,lossless,hires}` | 请求音质，默认 `lossless` |
| `-o, --outdir DIR` | 保存目录，默认 `./songs_dir` |
| `-w, --workers N` | 并发线程数，默认 5 |
| `--dry-run` | 只列出歌曲和接口实际返回的音质，不下载 |
| `-h, --help` | 查看完整帮助 |

保存路径：

```
songs_dir/<专辑或歌单名>/<序号>. <歌名> - <歌手>.flac
```

单曲链接会优先保存到该单曲所属专辑的目录；没有专辑信息时使用歌名作为目录名。
已经下载完成的文件会自动跳过；中断后重新运行即可，未完成的文件会重新下载。

### 获取无损 FLAC（需要 VIP）

1. 用浏览器登录 <https://music.163.com>；
2. 按 F12 → Application / 存储 → Cookies → `https://music.163.com` → 复制 `MUSIC_U` 的值；
3. 任选一种方式提供 cookie：

```powershell
# 1) 命令行参数
python main.py "https://music.163.com/#/album?id=198202188" --cookie "MUSIC_U=复制的值"

# 2) 写入脚本目录下的 cookie.txt（文件内容就是 MUSIC_U=...）
# 3) 环境变量（Windows PowerShell）
$env:NETEASE_COOKIE = "MUSIC_U=复制的值"
python main.py "https://music.163.com/#/album?id=198202188"
```

> `cookie.txt`、`download.log`、`songs_dir/` 和 `*.part` 已加入 `.gitignore`，不会被提交。
> 请不要把 cookie 分享给他人；cookie 泄露等同于账号登录态泄露。

### 音质说明

- `--level lossless`（默认）请求无损；`hires` 请求 Hi-Res，但同样需要账号具备相应权限。
- 接口可能根据账号权限、地区和歌曲版权自动降级；用 `--dry-run` 可以查看每首歌
  **实际返回**的格式、码率和音质等级。
- 没有 FLAC 的歌曲默认跳过；加 `-m / --mp3` 后会连同 MP3 一起保存。

### 示例输出

```
[INFO] 专辑: 四海五洲 以及其他星塵版重製曲 - TOPKINGCREAM
[INFO] 共 5 首歌曲:
[INFO]   01. 白色風車 - TOPKINGCREAM
[INFO]   ...
[INFO] 保存目录: .../songs_dir/四海五洲 以及其他星塵版重製曲
[INFO] 检测到 5 首无损资源, 开始下载 FLAC。
[INFO] 下载完成: 01. 白色風車 - TOPKINGCREAM.flac (27.9 MB, lossless)
[INFO] 共 5 首歌曲: FLAC 5 首, MP3 0 首, 已存在跳过 0 首, 下载失败 0 首, 无 FLAC 跳过 0 首, 无资源 0 首
```

## 常见问题

**下载到的全是 MP3？**
说明当前请求没有拿到无损资源。请确认账号已开通 VIP、`MUSIC_U` 未过期，并且确实传入了
cookie。可先用 `--dry-run` 检查接口返回的音质。

**提示“无版权 / 已下架”？**
部分歌曲受版权、地区或下架影响，接口不会返回下载地址，只能跳过。

**为什么中断后没有断点续传？**
当前实现会跳过已完成的文件，但未完成的 `.part` 文件会重新下载，暂不支持 HTTP Range 续传。

**文件名中的特殊字符怎么处理？**
文件名会做 NFKC 规范化，并替换 Windows 保留字符（`\ / : * ? " < > |`），保证可以保存。

**Windows 控制台中文乱码？**
程序启动时会自动把控制台代码页切换为 UTF-8；如果仍有乱码，可以手动执行 `chcp 65001`，
或使用 Windows Terminal。

## 测试

```bash
python -m unittest test.py -v
```

测试分为纯函数测试和联网测试；联网失败时会自动跳过，不会让整个测试失败。
运行测试会在当前目录生成 `download.log`（已被忽略）。

## 项目结构

```
main.py                  # 主程序（网易云音乐接口）
test.py                  # 单元测试 + 联网测试
main_original_baidu.py   # 原版百度接口实现，仅作备份
requirements.txt         # 依赖
```

## TODO

- 大歌单（>1000 首）的分页拉取
- 下载断点续传（HTTP Range）
- 为 FLAC 写入封面、歌词和标签
- 解析分享文本、短链接等更多链接形式

## License

MIT License

Copyright (c) 2016 YongHaoHu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
