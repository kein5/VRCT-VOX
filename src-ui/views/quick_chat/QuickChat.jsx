import { useEffect, useRef, useState } from 'react';
import { useI18n } from '@useI18n';
import { quickChatBridge } from '../../logics/quickChat/bridge';
import styles from './QuickChat.module.scss';

export const QuickChat = ({ bridge = quickChatBridge }) => {
    const { t, i18n } = useI18n();
    const [value, setValue] = useState(''), [pending, setPending] = useState(false), [error, setError] = useState(null);
    const [context, setContext] = useState({ enter_to_send: true, clear_on_send: true });
    const field = useRef(null), composing = useRef(false), sending = useRef(false);
    useEffect(() => {
        let disposed = false;
        const focus = async () => {
            try {
                const next = await bridge.context();
                if (disposed) return;
                setContext(next);
                await i18n.changeLanguage(next.language);
                field.current?.focus();
            } catch { if (!disposed) setError('quick_chat_not_ready'); }
        };
        focus();
        const off = bridge.onOpen(focus);
        window.addEventListener('focus', focus);
        return () => { disposed = true; off.then(fn => fn()); window.removeEventListener('focus', focus); };
    }, [bridge, i18n]);
    const submit = async () => {
        if (sending.current || composing.current || !value.trim()) return;
        sending.current = true; setPending(true); setError(null);
        // An unanswered handoff stays pending: never retry or clear a possibly sent message.
        const timer = setTimeout(() => setError('quick_chat_unconfirmed'), 5000);
        try {
            const ok = await bridge.submit({ id: crypto.randomUUID(), message: value });
            if (ok) { if (context.clear_on_send) setValue(''); setError(null); }
            else setError('quick_chat_not_ready');
        } catch (error) {
            const code = String(error);
            setError(['quick_chat_not_ready', 'quick_chat_busy'].includes(code) ? code : 'quick_chat_not_ready');
        } finally { clearTimeout(timer); sending.current = false; setPending(false); field.current?.focus(); }
    };
    return <main className={styles.container} onKeyDown={event => {
        if (event.key === 'Escape' && !composing.current && !event.nativeEvent.isComposing && event.keyCode !== 229) {
            event.preventDefault();
            bridge.hide().catch(() => setError('quick_chat_not_ready'));
        }
    }}>
        <textarea ref={field} aria-label={t('quick_chat.message')} value={value} readOnly={pending}
            onChange={event => { setValue(event.target.value); setError(null); }}
            onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
            onKeyDown={event => {
                if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return;
                if (event.key === 'Enter' && !event.shiftKey && context.enter_to_send) { event.preventDefault(); if (!event.repeat) submit(); }
            }} />
        <div className={styles.actions}>
            <span role={error ? 'alert' : 'status'}>{error ? t(`quick_chat.${error}`) : pending ? t('quick_chat.sending') : t('quick_chat.hint')}</span>
            <button type="button" disabled={pending || !value.trim()} onClick={submit}>{t('quick_chat.send')}</button>
        </div>
    </main>;
};
