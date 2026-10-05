import type { ThemeConfig } from "antd";

export const corporateTheme: ThemeConfig = {
  token: {
    colorPrimary: "#174ea6",
    colorInfo: "#174ea6",
    colorSuccess: "#237a57",
    colorWarning: "#a15c00",
    colorError: "#b42318",
    colorText: "#182230",
    colorTextSecondary: "#536273",
    colorBgLayout: "#f3f6f9",
    borderRadius: 8,
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    controlHeight: 40,
  },
  components: {
    Layout: { siderBg: "#0d2340", headerBg: "#ffffff", bodyBg: "#f3f6f9" },
    Menu: { darkItemBg: "#0d2340", darkItemSelectedBg: "#174ea6", darkItemHoverBg: "#14375f" },
    Card: { headerBg: "#ffffff" },
    Table: { headerBg: "#edf2f7", headerColor: "#243b53" },
  },
};
