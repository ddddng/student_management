// script.js

// Example: Add confirmation dialog before submitting delete forms
document.addEventListener('DOMContentLoaded', function() {
    const deleteForms = document.querySelectorAll('form[action*="/delete/"]'); // Select forms whose action contains '/delete/'
    deleteForms.forEach(form => {
        form.addEventListener('submit', function(event) {
            // The confirmation is already handled by the 'onsubmit' attribute in HTML,
            // but you could add more complex JS confirmation logic here if needed.
            // For example, using Bootstrap modals for confirmation.

            // const confirmed = confirm('Are you sure you want to delete this item? This action cannot be undone.');
            // if (!confirmed) {
            //     event.preventDefault(); // Stop form submission if not confirmed
            // }
            console.log('Delete form submitted for action:', form.action);
        });
    });

    // Example: Initialize Bootstrap tooltips if you use them
    // Make sure you add the `data-bs-toggle="tooltip"` attribute to elements in HTML
    // var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
    // var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
    //   return new bootstrap.Tooltip(tooltipTriggerEl)
    // })

    console.log("Student Management System JS Initialized.");
});

// Add any other custom JavaScript interactions here.
// For example, client-side validation, AJAX requests, dynamic content updates, etc.