# Quarto + VS Code + GitHub Pages 操作手册

这份文档总结了我们今天从零搭建一个 Quarto 网站，并把它发布到 GitHub Pages 的完整流程。内容尽量写得细一点，让没有做过的同学也能一步一步照着完成。

适用场景：

- 老师要求用 Quarto 做一个简单网站
- 用 VS Code 编辑
- 用 GitHub Pages 发布
- 最后把网站链接发给老师

最终目标：

- 本地能预览网站
- GitHub 上有 repo
- GitHub Pages 成功发布
- 拿到一个公开 URL

---

## 1. 先准备好这些东西

开始前先确认电脑上有：

- VS Code
- Git
- Quarto
- GitHub 账号

可以在终端里检查：

```bash
git --version
quarto --version
```

如果 `quarto --version` 能显示版本号，就说明 Quarto 已经装好了。

---

## 2. 创建网站项目文件夹

先新建一个文件夹，比如放在桌面：

```bash
mkdir ~/Desktop/my-website
cd ~/Desktop/my-website
```

然后用 VS Code 打开这个文件夹。

---

## 3. 用 Quarto 初始化一个网站项目

在 VS Code 的终端里运行：

```bash
quarto create project website .
```

意思是：在当前目录创建一个 Quarto 网站项目。

执行完成后，一般会看到这些文件：

- `_quarto.yml`
- `index.qmd`
- `about.qmd`
- `styles.css`

说明框架已经搭好了。

---

## 4. 理解几个关键文件

### `_quarto.yml`

这是网站配置文件，用来控制：

- 网站类型
- 网站标题
- 顶部导航栏
- 主题
- CSS
- 输出目录

### `index.qmd`

这是首页内容。

### `about.qmd`

这是 About 页面内容。

### `styles.css`

这是自定义样式文件，如果想改颜色、字体、间距，可以在这里加 CSS。

---

## 5. 把网站输出目录改成 `docs`

这一步非常重要，因为 GitHub Pages 可以直接从 repo 里的 `docs/` 文件夹发布网站。

打开 `_quarto.yml`，改成下面这种结构：

```yaml
project:
  type: website
  output-dir: docs

website:
  title: "hello"
  navbar:
    left:
      - href: index.qmd
        text: Home
      - href: about.qmd
        text: About

format:
  html:
    theme:
      - cosmo
      - brand
    css: styles.css
    toc: true
```

这里最关键的是这一行：

```yaml
output-dir: docs
```

它表示 Quarto 渲染后的网站文件会输出到 `docs/` 文件夹。

---

## 6. 先在本地预览网站

在终端里运行：

```bash
quarto preview
```

运行后终端会出现一个本地地址，例如：

```text
http://localhost:3209/
```

或者：

```text
http://localhost:4473/
```

把这个地址复制到浏览器里，就能看到你的网站。

这一步的作用是：

- 检查网站能不能正常显示
- 看看首页和 About 页面是否正确
- 修改内容后能实时预览

如果想停止本地预览，在终端里按：

```bash
Ctrl + C
```

---

## 7. 正式生成网站文件

当你确认页面没问题后，运行：

```bash
quarto render
```

这一步会把 `.qmd` 文件变成真正的网站文件，并输出到 `docs/`。

执行完之后，你的项目目录里应该会出现：

- `docs/index.html`
- `docs/about.html`
- `docs/site_libs/...`

如果有 `docs/` 文件夹，说明这一步成功了。

---

## 8. 创建 GitHub repo

去 GitHub 新建一个 repository。

建议设置：

- Repository name: 自己起一个名字，比如 `Fintech-533`
- Visibility: `Public`

建 repo 时建议不要勾选：

- `Add a README file`
- `.gitignore`
- `license`

因为你本地已经有项目文件了，建一个空 repo 最方便。

---

## 9. 把本地网站推到 GitHub

假设你的 GitHub repo 地址是：

```text
https://github.com/jxin00721/Fintech-533.git
```

那么在本地项目目录终端里依次运行：

```bash
git init
git add .
git commit -m "Initial Quarto website"
git branch -M main
git remote add origin https://github.com/jxin00721/Fintech-533.git
git push -u origin main
```

如果之前已经初始化过 git，就不用重复 `git init`。  
如果 remote 已经存在，也不要重复 `git remote add origin ...`。

常见更新流程会变成：

```bash
git add .
git commit -m "Update site"
git push
```

---

## 10. 开启 GitHub Pages

push 成功之后，去 GitHub repo 页面，按下面步骤设置：

1. 打开你的 repo
2. 点击 `Settings`
3. 在左侧找到 `Pages`
4. 在 `Build and deployment` 下设置：

- `Source`: `Deploy from a branch`
- `Branch`: `main`
- `Folder`: `/docs`

5. 点击 `Save`

这一步非常关键，因为老师的要求就是让 GitHub Pages 从你放网站文件的目录发布。我们这里用的就是 `docs/`。

---

## 11. 等待网站发布

保存后等待 1 到 3 分钟，然后刷新 GitHub Pages 页面。

如果成功，你会看到类似：

```text
Your site is live at https://你的用户名.github.io/仓库名/
```

比如我们实际成功的例子是：

```text
https://jxin00721.github.io/Fintech-533/
```

这说明：

- 网站已经部署成功
- GitHub Pages 设置正确
- 现在可以公开访问

---

## 12. 给网站加一张图片

老师最后还要求：

- add a picture
- push to Git
- message me

所以还要补一张图片。

### 第一步：准备图片

在项目目录里新建一个文件夹：

```text
images/
```

然后把一张图片放进去，例如：

```text
images/me.jpg
```

### 第二步：在首页插入图片

打开 `index.qmd`，加入：

```markdown
![](images/me.jpg){width=40%}
```

一个更完整的首页示例可以写成：

```markdown
---
title: "Fintech533 Pairs Trading"
---

Welcome to my Quarto website for Fintech 533.

![](images/me.jpg){width=40%}

This site is for practicing GitHub Pages and Quarto.
```

### 第三步：重新生成并 push

```bash
quarto render
git add .
git commit -m "Add image to site"
git push
```

然后等一两分钟，刷新网站页面，就能看到图片了。

---

## 13. 最后把 URL 发给老师

老师最后要的是你的网站链接。

可以直接发：

```text
https://你的用户名.github.io/仓库名/
```

也可以礼貌一点发成：

```text
Hi Professor, here is my site URL:
https://你的用户名.github.io/仓库名/
```

---

## 14. 以后每次更新网站怎么做

以后如果你改了 `index.qmd`、`about.qmd`、图片或者 CSS，更新流程就是固定这几步：

```bash
quarto render
git add .
git commit -m "Update site"
git push
```

然后等待 GitHub Pages 自动重新部署。

---

## 15. 常见问题

### 问题 1：GitHub Pages 页面显示 disabled

原因：

- repo 里还没有内容
- 或者还没有 `docs/`

解决：

先本地运行：

```bash
quarto render
```

再把生成的 `docs/` push 到 GitHub。

### 问题 2：网站链接打不开

可能原因：

- GitHub Pages 还在部署
- `docs/` 里没有 `index.html`
- Pages 设置不是 `main` + `/docs`

解决：

- 等 1 到 3 分钟再刷新
- 检查 `docs/index.html` 是否存在
- 检查 `Settings > Pages` 的设置

### 问题 3：本地可以 preview，但 GitHub 上没更新

原因：

- 只运行了 `quarto preview`
- 没有运行 `quarto render`
- 没有 `git push`

解决：

```bash
quarto render
git add .
git commit -m "Update site"
git push
```

### 问题 4：导航栏里 About 显示不正常

最好在 `_quarto.yml` 里写完整格式：

```yaml
navbar:
  left:
    - href: index.qmd
      text: Home
    - href: about.qmd
      text: About
```

不要只写一行：

```yaml
- about.qmd
```

虽然有时也能工作，但不够清晰。

---

## 16. 一套最短可复用流程

如果以后要快速重复这件事，可以直接记这套：

```bash
mkdir my-website
cd my-website
quarto create project website .
```

修改 `_quarto.yml`：

```yaml
project:
  type: website
  output-dir: docs
```

然后：

```bash
quarto preview
quarto render
git init
git add .
git commit -m "Initial site"
git branch -M main
git remote add origin 你的repo地址
git push -u origin main
```

最后去 GitHub：

- `Settings`
- `Pages`
- `Source = Deploy from a branch`
- `Branch = main`
- `Folder = /docs`

完成后就能拿到公开网站链接。

---

## 17. 这次我们实际完成了什么

这次实际完成的闭环是：

1. 用 Quarto 在本地创建了网站项目
2. 在 VS Code 中编辑 `_quarto.yml`、`index.qmd`、`about.qmd`
3. 把输出目录改成了 `docs`
4. 用 `quarto preview` 在本地预览
5. 用 `quarto render` 生成网站
6. 把项目 push 到 GitHub repo
7. 在 GitHub Pages 里选择 `main` 分支的 `/docs`
8. 成功得到公开网址
9. 按老师要求，下一步只需要补图片并再次 push

---

## 18. 一句话总结

这套流程的核心其实很简单：

> 用 Quarto 写网站内容，用 VS Code 编辑，用 `quarto render` 生成 `docs/`，再让 GitHub Pages 从 `main/docs` 发布。

