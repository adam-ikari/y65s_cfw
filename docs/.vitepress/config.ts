import { defineConfig } from "vitepress";

// 站点部署在 https://adam-ikari.github.io/y65s_cfw/ ，所以 base 要带仓库名。
export default defineConfig({
  title: "YD-Y65S 工具",
  description:
    "YD-Y65S 键盘屏幕上那条和系统音量对不上的音量条：一键修复。固件补丁、备份与校验都在工具里。",
  lang: "zh-CN",
  base: "/y65s_cfw/",
  cleanUrls: true,
  lastUpdated: true,
  appearance: "dark",
  themeConfig: {
    logo: "/logo.svg",
    siteTitle: "YD-Y65S 工具",
    nav: [
      { text: "首页", link: "/" },
      { text: "怎么修", link: "/how-to" },
      { text: "补丁", link: "/patches" },
      { text: "常见问题", link: "/faq" },
    ],
    sidebar: [
      {
        text: "使用",
        items: [
          { text: "首页", link: "/" },
          { text: "怎么修", link: "/how-to" },
          { text: "补丁说明", link: "/patches" },
          { text: "常见问题", link: "/faq" },
        ],
      },
      {
        text: "原理",
        items: [
          { text: "两芯片架构", link: "/two-chip-architecture" },
          { text: "仓库", link: "https://github.com/adam-ikari/y65s_cfw" },
        ],
      },
    ],
    socialLinks: [{ icon: "github", link: "https://github.com/adam-ikari/y65s_cfw" }],
    outline: { level: [2, 3] },
    docFooter: { prev: true, next: true },
    footer: {
      message: "固件里的绝大多数字节仍然是厂商原厂固件；本项目只做可审计的字节级补丁。",
      copyright: "YD-Y65S (258A:019D) · Sinowealth SH68F90/A",
    },
  },
});
