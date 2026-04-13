/**
 * J-Finance - Authentication Module
 * Gerencia a autenticação do Firebase no frontend
 * 
 * NOTA: A inicialização do Firebase é feita no base.html
 * Esta biblioteca fornece funções auxiliares para autenticação
 */

(function() {
    'use strict';

    /**
     * Mostra uma mensagem de toast
     * @param {string} message - Mensagem a ser exibida
     * @param {string} type - Tipo do toast ('success' ou 'error')
     */
    function showToast(message, type = 'success') {
        // Cria o container se não existir
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.style.cssText = `
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 9999;
                display: flex;
                flex-direction: column;
                gap: 8px;
            `;
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        const bgColor = type === 'success' ? '#2D7A4F' : '#9B2335';
        toast.style.cssText = `
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            box-shadow: 0 12px 32px rgba(13,27,42,0.18);
            animation: slideUp 0.3s ease forwards;
            background: ${bgColor};
            color: white;
        `;
        toast.textContent = message;
        container.appendChild(toast);

        setTimeout(() => {
            toast.remove();
        }, 4000);
    }

    /**
     * Traduz códigos de erro do Firebase para mensagens em português
     * @param {string} code - Código de erro do Firebase
     * @returns {string} Mensagem traduzida
     */
    function translateAuthError(code) {
        const errorMessages = {
            // Erros de login
            'auth/wrong-password': 'Senha incorreta.',
            'auth/user-not-found': 'E-mail não encontrado.',
            'auth/invalid-email': 'E-mail inválido.',
            'auth/too-many-requests': 'Muitas tentativas. Tente novamente em alguns minutos.',
            'auth/user-disabled': 'Esta conta foi desativada.',
            'auth/invalid-credential': 'E-mail ou senha incorretos.',
            
            // Erros de cadastro
            'auth/email-already-in-use': 'Este e-mail já está em uso.',
            'auth/weak-password': 'A senha deve ter pelo menos 6 caracteres.',
            'auth/operation-not-allowed': 'Operação não permitida.',
            
            // Erros gerais
            'auth/network-request-failed': 'Erro de conexão. Verifique sua internet.',
            'auth/timeout': 'Tempo esgotado. Tente novamente.',
            'auth/popup-closed-by-user': 'Login cancelado.',
            'auth/cancelled-popup-request': 'Múltiplas solicitações de login.',
            'auth/popup-blocked': 'Popup bloqueado pelo navegador.',
            
            // Erros de redefinição de senha
            'auth/missing-email': 'E-mail não fornecido.',
            'auth/invalid-action-code': 'Link inválido ou expirado.',
            'auth/expired-action-code': 'Link expirado. Solicite um novo.'
        };

        return errorMessages[code] || 'Ocorreu um erro. Tente novamente.';
    }

    /**
     * Aguarda a inicialização do Firebase Auth
     * @returns {Promise} Promise que resolve quando o auth estiver disponível
     */
    function waitForAuth() {
        return new Promise((resolve, reject) => {
            let attempts = 0;
            const maxAttempts = 50; // 5 segundos máximo
            
            const checkAuth = () => {
                if (window.firebaseAuth) {
                    resolve(window.firebaseAuth);
                } else if (attempts >= maxAttempts) {
                    reject(new Error('Firebase Auth não inicializado'));
                } else {
                    attempts++;
                    setTimeout(checkAuth, 100);
                }
            };
            
            checkAuth();
        });
    }

    // Expõe as funções globalmente
    window.JFinanceAuth = {
        showToast,
        translateAuthError,
        waitForAuth
    };

    // Adiciona a animação de slideUp ao documento
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideUp {
            from { transform: translateY(20px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
    `;
    document.head.appendChild(style);
})();
