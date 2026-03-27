document.addEventListener('click', function(event) {
    if (!event.target.closest('.dropdown')) {
        document.querySelector('.dropdown-content').classList.remove('show');
    }
});