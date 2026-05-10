(function () {
    const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const MONTHS_LONG = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ];
    const SVG_NS = 'http://www.w3.org/2000/svg';
    const CELL_SIZE = 14;
    const CELL_GAP = 2;
    const DAY_LABEL_WIDTH = 30;
    const MONTH_LABEL_HEIGHT = 20;

    function onReady(fn) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fn, { once: true });
        } else {
            fn();
        }
    }

    function readJson(id) {
        const node = document.getElementById(id);
        if (!node || !node.textContent.trim()) return {};
        try {
            return JSON.parse(node.textContent);
        } catch (_) {
            return {};
        }
    }

    function getCSSVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    function dateKey(date) {
        return date.toISOString().split('T')[0];
    }

    function rangeForCountData(data) {
        const dates = Object.keys(data).map(function (d) { return new Date(d); });
        if (dates.length === 0) return null;

        let minDate = new Date(Math.min.apply(null, dates.map(function (d) { return d.getTime(); })));
        const maxDate = new Date(Math.max.apply(null, dates.map(function (d) { return d.getTime(); })));
        const minRangeDate = new Date(maxDate);
        minRangeDate.setFullYear(minRangeDate.getFullYear() - 1);
        if (minDate > minRangeDate) minDate = minRangeDate;

        return { minDate: minDate, maxDate: maxDate };
    }

    function rangeForReviewData(data) {
        const dates = Object.keys(data).map(function (d) { return new Date(d); });
        let minDate;
        const maxDate = new Date();

        if (dates.length > 0) {
            minDate = new Date(Math.min.apply(null, dates.map(function (d) { return d.getTime(); })));
        } else {
            minDate = new Date();
            minDate.setFullYear(minDate.getFullYear() - 1);
        }

        const minRangeDate = new Date(maxDate);
        minRangeDate.setFullYear(minRangeDate.getFullYear() - 1);
        if (minDate > minRangeDate) minDate = minRangeDate;

        return { minDate: minDate, maxDate: maxDate };
    }

    function weeksBetween(minDate, maxDate, mapCell) {
        const startDate = new Date(minDate);
        startDate.setDate(startDate.getDate() - startDate.getDay());

        const endDate = new Date(maxDate);
        endDate.setDate(endDate.getDate() + (6 - endDate.getDay()));

        const weeks = [];
        let currentWeek = [];
        const currentDate = new Date(startDate);

        while (currentDate <= endDate) {
            const dayOfWeek = currentDate.getDay();
            currentWeek.push(mapCell(new Date(currentDate), dayOfWeek));

            if (dayOfWeek === 6) {
                weeks.push(currentWeek);
                currentWeek = [];
            }

            currentDate.setDate(currentDate.getDate() + 1);
        }

        if (currentWeek.length > 0) weeks.push(currentWeek);
        return weeks;
    }

    function createWrapper() {
        const wrapper = document.createElement('div');
        wrapper.style.display = 'flex';
        wrapper.style.gap = '4px';
        wrapper.style.alignItems = 'flex-start';
        return wrapper;
    }

    function createSvg(width, height) {
        const svg = document.createElementNS(SVG_NS, 'svg');
        svg.setAttribute('width', width);
        svg.setAttribute('height', height);
        svg.setAttribute('class', 'dark:text-gray-300');
        return svg;
    }

    function appendDayLabels(wrapper) {
        const height = MONTH_LABEL_HEIGHT + 7 * (CELL_SIZE + CELL_GAP) + 10;
        const svg = createSvg(DAY_LABEL_WIDTH, height);
        svg.style.position = 'sticky';
        svg.style.left = '0';
        svg.style.zIndex = '20';
        svg.style.backgroundColor = 'var(--heatmap-label-bg)';
        svg.style.flexShrink = '0';

        for (let i = 0; i < 7; i += 1) {
            const text = document.createElementNS(SVG_NS, 'text');
            text.setAttribute('x', 2);
            text.setAttribute('y', MONTH_LABEL_HEIGHT + i * (CELL_SIZE + CELL_GAP) + CELL_SIZE - 2);
            text.setAttribute('font-size', '11');
            text.setAttribute('fill', 'currentColor');
            text.setAttribute('class', 'dark:text-gray-400');
            text.textContent = DAYS[i];
            svg.appendChild(text);
        }

        wrapper.appendChild(svg);
    }

    function appendMonthLabels(svg, weeks) {
        let lastMonth = -1;
        weeks.forEach(function (week, w) {
            const firstDay = week[0].date;
            const month = firstDay.getMonth();
            if (month === lastMonth) return;

            const text = document.createElementNS(SVG_NS, 'text');
            text.setAttribute('x', w * (CELL_SIZE + CELL_GAP));
            text.setAttribute('y', 14);
            text.setAttribute('font-size', '11');
            text.setAttribute('fill', 'currentColor');
            text.setAttribute('class', 'dark:text-gray-400');
            text.textContent = MONTHS_SHORT[month];
            svg.appendChild(text);
            lastMonth = month;
        });
    }

    function appendCell(svg, cell, w, d, color, titleText) {
        const rect = document.createElementNS(SVG_NS, 'rect');
        rect.setAttribute('x', w * (CELL_SIZE + CELL_GAP));
        rect.setAttribute('y', MONTH_LABEL_HEIGHT + d * (CELL_SIZE + CELL_GAP));
        rect.setAttribute('width', CELL_SIZE);
        rect.setAttribute('height', CELL_SIZE);
        rect.setAttribute('fill', color);
        rect.setAttribute('stroke', getCSSVar('--heatmap-stroke'));
        rect.setAttribute('stroke-width', '0.5');
        rect.setAttribute('rx', '2');
        rect.setAttribute('class', 'cursor-pointer hover:stroke-gray-400 dark:stroke-gray-600');

        const title = document.createElementNS(SVG_NS, 'title');
        title.textContent = titleText(cell);
        rect.appendChild(title);
        svg.appendChild(rect);
    }

    function scrollRight(id) {
        const scrollContainer = document.getElementById(id);
        if (!scrollContainer) return;
        setTimeout(function () {
            scrollContainer.scrollLeft = scrollContainer.scrollWidth;
        }, 0);
    }

    function colorScale(maxValue) {
        const colors = [
            getCSSVar('--heatmap-empty'),
            getCSSVar('--heatmap-scale-1'),
            getCSSVar('--heatmap-scale-2'),
            getCSSVar('--heatmap-scale-3'),
            getCSSVar('--heatmap-scale-4')
        ];

        return function (value) {
            if (value === 0 || maxValue === 0) return colors[0];
            const ratio = value / maxValue;
            const index = Math.ceil(ratio * (colors.length - 1));
            return colors[Math.min(index, colors.length - 1)];
        };
    }

    function renderHeatmap(data) {
        const container = document.getElementById('heatmap');
        if (!container) return;
        const range = rangeForCountData(data);
        if (!range) return;

        const weeks = weeksBetween(range.minDate, range.maxDate, function (date, dayOfWeek) {
            const key = dateKey(date);
            return { date: date, dateStr: key, count: data[key] || 0, day: dayOfWeek };
        });
        const scale = colorScale(Math.max.apply(null, Object.values(data)));
        const wrapper = createWrapper();
        const svg = createSvg(
            weeks.length * (CELL_SIZE + CELL_GAP) + 10,
            MONTH_LABEL_HEIGHT + 7 * (CELL_SIZE + CELL_GAP) + 10
        );

        appendDayLabels(wrapper);
        appendMonthLabels(svg, weeks);
        weeks.forEach(function (week, w) {
            week.forEach(function (cell, d) {
                appendCell(svg, cell, w, d, scale(cell.count), function (c) {
                    const dayName = DAYS[c.date.getDay()];
                    const monthName = MONTHS_LONG[c.date.getMonth()];
                    const year = c.date.getFullYear();
                    return dayName + ', ' + monthName + ' ' + c.date.getDate() + ', ' + year + ': '
                        + c.count + ' highlight' + (c.count !== 1 ? 's' : '');
                });
            });
        });

        container.textContent = '';
        wrapper.appendChild(svg);
        container.appendChild(wrapper);
        scrollRight('heatmap-container');
    }

    function renderReviewHeatmap(data) {
        const container = document.getElementById('review-heatmap');
        if (!container) return;

        const range = rangeForReviewData(data);
        const weeks = weeksBetween(range.minDate, range.maxDate, function (date, dayOfWeek) {
            const key = dateKey(date);
            return { date: date, dateStr: key, hasReview: data[key] === 1, day: dayOfWeek };
        });
        const wrapper = createWrapper();
        const svg = createSvg(
            weeks.length * (CELL_SIZE + CELL_GAP) + 10,
            MONTH_LABEL_HEIGHT + 7 * (CELL_SIZE + CELL_GAP) + 10
        );
        const noReviewColor = getCSSVar('--heatmap-empty');
        const reviewedColor = getCSSVar('--heatmap-reviewed');

        appendDayLabels(wrapper);
        appendMonthLabels(svg, weeks);
        weeks.forEach(function (week, w) {
            week.forEach(function (cell, d) {
                appendCell(svg, cell, w, d, cell.hasReview ? reviewedColor : noReviewColor, function (c) {
                    const dayName = DAYS[c.date.getDay()];
                    const monthName = MONTHS_LONG[c.date.getMonth()];
                    const year = c.date.getFullYear();
                    const status = c.hasReview ? 'Reviewed \u2713' : 'No review';
                    return dayName + ', ' + monthName + ' ' + c.date.getDate() + ', ' + year + ': ' + status;
                });
            });
        });

        container.textContent = '';
        wrapper.appendChild(svg);
        container.appendChild(wrapper);
        scrollRight('review-heatmap-container');
    }

    onReady(function () {
        const heatmapData = readJson('dashboard-heatmap-data');
        if (Object.keys(heatmapData).length > 0) renderHeatmap(heatmapData);

        const reviewHeatmapData = readJson('dashboard-review-heatmap-data');
        if (Object.keys(reviewHeatmapData).length > 0) renderReviewHeatmap(reviewHeatmapData);
    });
})();
