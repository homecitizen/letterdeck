# 🎬 LetterDeck — Smart Cinema & Music Desk Display
## ESP32-2432S028 (CYD 2.8" ST7789 320×240 + Touch XPT2046)

Dispositivo de sobremesa inteligente y dual que combina un **recomendador de cine estilo Letterboxd** con un **visualizador interactivo de Apple Music / Spotify / Windows Media**.

![Vista Previa Letterboxd](tools/preview_cinema.png)

---

## ✨ Características principales

1. **Modo Dual Cine + Música (Híbrido Inteligente)**:
   - **`[AUTO]`**: En reposo muestra las recomendaciones cinematográficas del día. Cuando empieza a sonar música en tu ordenador, la pantalla conmuta automáticamente en tiempo real al visualizador de Now Playing con controles táctiles (Play/Pausa, Siguiente, Anterior). Al detenerse la música, vuelve a Cine de manera fluida.
   - **`[CINE]`**: Modo exclusivo de cine independiente.
   - **`[MUS]`**: Modo exclusivo de música con pantalla de espera decorativa.
2. **Calendario Dinámico 365 Días + Temporadas Especiales**:
   - 📅 **Película del Día**: Algoritmo matemático que destaca una obra maestra cada día del año con su fecha en pantalla (ej: `31 OCT`).
   - 🎃 **Especial Halloween / Terror** *(15 Oct – 4 Nov)*: *The Shining, Halloween, Scream, Psycho, Alien, The Thing, The Silence of the Lambs, Hereditary...*
   - 🎄 **Especial Navidad / Invierno** *(1 Dic – 6 Ene)*: *Die Hard, Home Alone, The Nightmare Before Christmas, It's a Wonderful Life...*
   - 🏆 **Temporada de Premios Oscar** *(15 Ene – 15 Mar)*: *Parasite, The Godfather, Whiplash, The Silence of the Lambs...*
   - ⭐ **Grandes Hitos Top Letterboxd** *(Resto del año)*: *Pulp Fiction, The Matrix, Interstellar, Blade Runner 2049, Fight Club...*
3. **Curiosidades de Rodaje, Citas Célebres y Sinopsis**:
   - Toca el área izquierda de la pantalla para alternar entre la cita icónica de la película, una anécdota real de rodaje o la sinopsis.
4. **Soporte Bilingüe Español / Inglés (`[ES]` / `[EN]`)**:
   - Selector táctil directo en la barra inferior o mediante el portal web de configuración.
   - Citas en versión original en inglés (*"Here's Johnny!"*, *"I'm gonna make him an offer he can't refuse"*), trivia traducida y etiquetas contextuales.
5. **Pósters Oficiales TMDb en Alta Calidad**:
   - Decodificación ultra-rápida en memoria flash mediante `TJpg_Decoder`.

---

## 🛠️ Estructura del proyecto

```
letterdeck/
├── platformio.ini              ← Configuración optimizada con driver ST7789 y librerías
├── src/
│   ├── main.cpp                ← Bucle principal, conmutador de modo, Wi-Fi y táctil
│   ├── config.h                ← Credenciales Wi-Fi, rotación, intervalo de cambio
│   ├── movies_db.h             ← Base de datos integrada con películas y curiosidades
│   ├── ui_cinema.h             ← Motor gráfico estilo Letterboxd con controles
│   ├── poster_fetcher.h        ← Descarga y renderizado de imágenes JPEG
│   └── touch_controller.h      ← Controlador táctil XPT2046 (bus HSPI)
├── pc/
│   ├── nowplaying.py           ← Puente en Python para Windows Media / Apple Music
│   ├── requirements.txt        ← Dependencias (winsdk, pillow, pyserial)
│   └── iniciar.bat             ← Lanzador rápido para segundo plano
└── tools/
    ├── preview_cinema.png      ← Muestra de la interfaz
    └── sync_letterboxd.py      ← Importador de listas de Letterboxd a JSON
```

---

## 🚀 Cómo ponerlo en marcha

### 1. Flashear el ESP32 CYD con PlatformIO
```powershell
pio run -t upload --upload-port COM3
```

### 2. Iniciar el puente de música en el PC (Windows)
```powershell
cd pc
pip install -r requirements.txt
python nowplaying.py
```
*¡Y listo! Al poner música en Apple Music o Spotify, LetterDeck mostrará la carátula y el título. Al pausarla, regresará al cine de forma automática.*

---

## 📂 Familia de proyectos relacionados

- 🎬 [**cyd-cinema**](https://github.com/homecitizen/cyd-cinema): Versión autónoma dedicada **exclusivamente a cine** (sin requerir ordenador ni música).
- 🎵 [**cyd-apple-music**](https://github.com/homecitizen/cyd-apple-music): Versión dedicada **exclusivamente a música** (pantalla Now Playing para escritorio con LED RGB ambiental).
