# codesubflags
Programming Plugin with Subflags for ComSSA ATR (CTF).
Built from https://github.com/adamlahbib/CTFd_Multi_Questions and used with CTFd v3.5.2

This was used in the 2023 ATR event ran on the 27th of May.
Opensourced on 29th as event is over.

Note the following change for challenges.html template in your CTFd theme.
```html
{% block entrypoint %}
        <script defer src="{{ url_for('views.themes', path='js/pages/challenges.js') }}"></script>
        <script defer src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/codemirror.min.js" integrity="sha512-8RnEqURPUc5aqFEN04aQEiPlSAdE0jlFS/9iGgUyNtwFnSKCXhmB6ZTNl7LnDtDWKabJIASzXrzD0K+LYexU9g==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
    <link defer rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/codemirror.min.css" integrity="sha512-uf06llspW44/LZpHzHT6qBOIVODjWtv4MxCricRxkzvopAlSWnTf6hpZTFxuuZcuNE9CBQhqE0Seu1CoRk84nQ==" crossorigin="anonymous" referrerpolicy="no-referrer" />
        <script defer src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/6.65.7/mode/python/python.min.js" integrity="sha512-2M0GdbU5OxkGYMhakED69bw0c1pW3Nb0PeF3+9d+SnwN1ryPx3wiDdNqK3gSM7KAU/pEV+2tFJFbMKjKAahOkQ==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
{% endblock %}
```
