import { NavLink, Outlet } from "react-router-dom";

const links = [
  ["/", "仪表盘"],
  ["/settings", "交易设置"],
  ["/strategy", "策略管理"],
  ["/orders", "订单记录"],
  ["/trades", "成交记录"],
  ["/events", "系统事件"],
];

export function App() {
  return (
    <div className="min-h-screen">
      <header className="flex items-center gap-6 border-b border-zinc-800 px-6 py-3">
        <strong className="text-emerald-400">newhbot</strong>
        <nav className="flex gap-4 text-sm">
          {links.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => (isActive ? "text-white" : "text-zinc-400 hover:text-white")}
              end={to === "/"}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  );
}
