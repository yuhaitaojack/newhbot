import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { App } from "./App";
import { DashboardPage } from "./pages/DashboardPage";
import { JsonListPage, StrategyPage } from "./pages/Lists";
import { SettingsPage } from "./pages/SettingsPage";
import "./index.css";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "strategy", element: <StrategyPage /> },
      { path: "orders", element: <JsonListPage path="/api/orders" title="订单记录" /> },
      { path: "trades", element: <JsonListPage path="/api/trades" title="成交记录" /> },
      { path: "events", element: <JsonListPage path="/api/events" title="系统事件" /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
