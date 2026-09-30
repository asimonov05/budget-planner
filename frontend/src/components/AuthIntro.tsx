import { ShieldCheck } from 'lucide-react'

export function AuthIntro() {
  return <section className="login-intro">
    <div className="brand brand--light">
      <div className="brand-mark">К</div>
      <div className="brand-copy"><strong>Контур</strong><span>Личный бюджет</span></div>
    </div>
    <div>
      <span className="login-kicker">Финансы без шума</span>
      <h1>Каждый рубль<br/>на своём месте.</h1>
      <p>Планируйте доходы, обязательства и большие цели — приватно, на своём сервере.</p>
    </div>
    <div className="privacy-note">
      <ShieldCheck/>
      <span>Данные остаются у вас<br/><small>Без облака и банковских подключений</small></span>
    </div>
  </section>
}
