import { ShieldCheck } from 'lucide-react'

export function AuthIntro() {
  const combined = import.meta.env.BASE_URL === '/budget/'
  return <section className="login-intro">
    <div className="brand brand--light">
      <div className="brand-mark">К</div>
      <div className="brand-copy"><strong>Контур</strong><span>{combined ? 'Все приложения' : 'Личный бюджет'}</span></div>
    </div>
    <div>
      <span className="login-kicker">{combined ? 'Одно пространство' : 'Финансы без шума'}</span>
      <h1>{combined ? <>Все важное<br/>в одном месте.</> : <>Каждый рубль<br/>на своём месте.</>}</h1>
      <p>{combined ? 'Войдите один раз, чтобы открыть бюджет и photo-access.' : 'Планируйте доходы, обязательства и большие цели — приватно, на своём сервере.'}</p>
    </div>
    <div className="privacy-note">
      <ShieldCheck/>
      <span>Данные остаются у вас<br/><small>Без облака и банковских подключений</small></span>
    </div>
  </section>
}
