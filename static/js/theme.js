/**
 * J-Finance - Theme Manager
 * Gerencia o tema claro/escuro da aplicação
 * Persiste a preferência do usuário em localStorage
 */

(function() {
    'use strict';

    // Chave usada no localStorage
    const STORAGE_KEY = 'jfinance-theme';

    // Elementos do DOM - Desktop
    const themeToggleBtn = document.getElementById('theme-toggle');
    const sunIcon = document.querySelector('.icon-sun');
    const moonIcon = document.querySelector('.icon-moon');

    // Elementos do DOM - Mobile
    const themeToggleBtnMobile = document.getElementById('theme-toggle-mobile');
    const sunIconMobile = document.querySelector('.icon-sun-mobile');
    const moonIconMobile = document.querySelector('.icon-moon-mobile');

    /**
     * Obtém o tema atual
     * @returns {string} 'light' ou 'dark'
     */
    function getCurrentTheme() {
        // Verifica se há preferência salva
        const savedTheme = localStorage.getItem(STORAGE_KEY);
        if (savedTheme) {
            return savedTheme;
        }

        // Verifica a preferência do sistema
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }

        return 'light';
    }

    /**
     * Aplica o tema ao documento
     * @param {string} theme - 'light' ou 'dark'
     */
    function applyTheme(theme) {
        const root = document.documentElement;

        if (theme === 'dark') {
            root.setAttribute('data-theme', 'dark');
        } else {
            root.removeAttribute('data-theme');
        }

        updateIcons(theme);
    }

    /**
     * Atualiza os ícones do botão de tema
     * @param {string} theme - 'light' ou 'dark'
     */
    function updateIcons(theme) {
        // Desktop icons
        if (sunIcon && moonIcon) {
            if (theme === 'dark') {
                // In dark mode, show sun icon (click to switch to light)
                sunIcon.style.display = 'block';
                moonIcon.style.display = 'none';
            } else {
                // In light mode, show moon icon (click to switch to dark)
                sunIcon.style.display = 'none';
                moonIcon.style.display = 'block';
            }
        }

        // Mobile icons
        if (sunIconMobile && moonIconMobile) {
            if (theme === 'dark') {
                // In dark mode, show sun icon (click to switch to light)
                sunIconMobile.style.display = 'block';
                moonIconMobile.style.display = 'none';
            } else {
                // In light mode, show moon icon (click to switch to dark)
                sunIconMobile.style.display = 'none';
                moonIconMobile.style.display = 'block';
            }
        }
    }

    /**
     * Alterna entre os temas
     */
    function toggleTheme() {
        const currentTheme = getCurrentTheme();
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';

        // Save preference
        localStorage.setItem(STORAGE_KEY, newTheme);

        // Apply new theme
        applyTheme(newTheme);
    }

    /**
     * Inicializa o gerenciador de tema
     */
    function init() {
        // Aplica o tema inicial
        const theme = getCurrentTheme();
        applyTheme(theme);

        // Add click listener to desktop toggle button
        if (themeToggleBtn) {
            themeToggleBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                toggleTheme();
            });
        }

        // Add click listener to mobile toggle button
        if (themeToggleBtnMobile) {
            themeToggleBtnMobile.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                toggleTheme();
            });
        }

        // Listen for system preference changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            // Only apply if user has no saved preference
            if (!localStorage.getItem(STORAGE_KEY)) {
                applyTheme(e.matches ? 'dark' : 'light');
            }
        });
    }

    // Inicializa quando o DOM estiver pronto
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
