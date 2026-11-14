import React, {useEffect, useState} from "react";
import {AtSign, Check, Link2, Pencil, UserRound} from "lucide-react";

type RequestFn = (path: string, options?: RequestInit) => Promise<any>;
type Profile = {
  id: number;
  username: string | null;
  email: string | null;
  email_verified: boolean;
  referral_code: string;
  created_at: string | null;
  providers: {telegram: boolean; yandex: boolean; vk: boolean; email: boolean; passkey: boolean};
};

const PROVIDERS: [keyof Profile["providers"], string][] = [
  ["email", "Электронная почта"],
  ["telegram", "Telegram"],
  ["yandex", "Яндекс ID"],
  ["vk", "VK ID"],
  ["passkey", "Ключ доступа"],
];

/** Display name and linked sign-in methods of the customer account. */
export function ProfileCard({request, onSaved}: {request: RequestFn; onSaved: () => void}) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [name, setName] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let live = true;
    request("/api/me/profile")
      .then((value: Profile) => {
        if (!live) return;
        setProfile(value);
        setName(value.username || "");
      })
      .catch((e: any) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [request]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const value: Profile = await request("/api/me/profile", {method: "PATCH", body: JSON.stringify({username: name.trim()})});
      setProfile(value);
      setName(value.username || "");
      setEditing(false);
      setNotice("Профиль сохранён");
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!profile)
    return (
      <section className="form-card profile-card" aria-busy={!error}>
        {error ? <p className="workspace-alert error" role="alert">{error}</p> : <div className="ui-skeleton" style={{height: 112}} />}
      </section>
    );

  const initials = (profile.username || profile.email || "U").trim().slice(0, 1).toUpperCase();
  return (
    <section className="form-card profile-card" aria-label="Профиль">
      <div className="profile-head">
        <span className="profile-avatar" aria-hidden="true">
          {initials}
        </span>
        <div className="profile-id">
          <strong>{profile.username || "Без имени"}</strong>
          <span>
            <AtSign aria-hidden="true" />
            {profile.email || "Email не указан"}
            {profile.email && <em data-ok={profile.email_verified || undefined}>{profile.email_verified ? "подтверждён" : "не подтверждён"}</em>}
          </span>
        </div>
        {!editing && (
          <button type="button" className="btn-ghost" onClick={() => setEditing(true)}>
            <Pencil aria-hidden="true" />
            Изменить имя
          </button>
        )}
      </div>
      {editing && (
        <form className="workspace-form profile-form" onSubmit={save}>
          <label className="field">
            Имя в кабинете
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={64} minLength={2} required autoComplete="nickname" autoFocus />
          </label>
          <div className="btn-row">
            <button className="btn-primary" disabled={busy || name.trim().length < 2}>
              <Check aria-hidden="true" />
              Сохранить
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={busy}
              onClick={() => {
                setEditing(false);
                setName(profile.username || "");
              }}
            >
              Отмена
            </button>
          </div>
        </form>
      )}
      <div className="profile-providers" aria-label="Способы входа">
        {PROVIDERS.map(([key, label]) => (
          <span key={key} className="profile-provider" data-on={profile.providers[key] || undefined}>
            {profile.providers[key] ? <Link2 aria-hidden="true" /> : <UserRound aria-hidden="true" />}
            {label}
            <b>{profile.providers[key] ? "подключён" : "не подключён"}</b>
          </span>
        ))}
      </div>
      {error && <p className="workspace-alert error" role="alert">{error}</p>}
      {notice && <p className="workspace-alert" role="status">{notice}</p>}
    </section>
  );
}
