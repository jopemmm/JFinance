# J-Finance

J-Finance é uma plataforma web focada em conteúdos avançados de matemática, incluindo análises quantitativas e materiais exclusivos. O projeto possui um blog público, uma área de cursos gratuitos para membros autenticados e um painel administrativo completo.

## Tecnologias Utilizadas

- **Backend:** Python com Flask
- **Banco de Dados & Autenticação:** Firebase (Firestore NoSQL e Firebase Auth)
- **Frontend:** Vanilla HTML5, CSS3 (Arquitetura por tokens e BEM), e JavaScript (ES6+). Templates via Jinja2.
- **Segurança e Proteção:** Otimizações CSRF, Rate Limiting (Flask-Limiter) e cabeçalhos de segurança via Flask-Talisman. Sanitização via Bleach.
- **Servidor:** Gunicorn para produção

## Principais Funcionalidades

- **Blog Público:** Sistema robusto para renderização de artigos com tags, visualizações e rich-text.
- **Área de Cursos Segura:** Plataforma de módulos liberada somente com login válido via Firebase.
- **Painel Admin Oculto:** Criação visualística de artigos e cursos integrados diretamente com o Firestore.
- **Modo Light / Dark OLED Escuro:** UX sem bibliotecas externas e blindado contra interrupções de carregamento na tela (anti-FOUC).

## Como rodar localmente

### 1. Pré-requisitos
- Python instalado
- Dependências da compilação virtualizadas
- Conta no [Firebase Console](https://console.firebase.google.com/) para dados

### 2. Instalação e Execução

```bash
# Clone o repositório
git clone https://github.com/SEU-USUARIO/j-finance.git
cd j-finance

# Crie e ative o ambiente virtual
python -m venv venv
# No Windows:
.\venv\Scripts\activate
# No Mac/Linux:
source venv/bin/activate

# Instale os requerimentos
pip install -r requirements.txt

# Copie o env de exemplo para preenchê-lo com suas senhas (Firebase)
copy .env.example .env

# Rode o app
python app.py
```
Após executar, o ambiente estará na portabilidade local em `http://127.0.0.1:5000`.

## Preparado para Deploy

O projeto conta com o arquivo `Procfile` incluído. Está totalmente otimizado e balanceado para deploy imediato no Railway, Render ou Heroku via integração GitHub. 

---
*Desenvolvido para divulgar conhecimento.*
