// Control LoveBot via Flask API
$(document).ready(function() {
    // Start/Stop Buttons
    $("#start-bot").click(function() {
        $.ajax({
            url: "/api/command",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({
                device_id: 1,
                command: "start"
            }),
            success: function(response) {
                $("#bot-status").text("Online").removeClass("text-danger").addClass("text-success");
            }
        });
    });

    $("#stop-bot").click(function() {
        $.ajax({
            url: "/api/command",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({
                device_id: 1,
                command: "stop"
            }),
            success: function(response) {
                $("#bot-status").text("Offline").removeClass("text-success").addClass("text-danger");
            }
        });
    });

    // Chart.js Analytics (Optional)
    const ctx = document.getElementById('usageChart').getContext('2d');
    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
            datasets: [{
                label: 'Daily Interactions',
                data: [12, 19, 3, 5, 2],
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
});