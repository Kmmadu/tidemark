/**
 * Network Traffic Particle System
 * Simulates data flow between network nodes
 */

class NetworkParticleSystem {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.particles = [];
        this.links = [];
        this.nodes = [];
        this.animationId = null;
        this.time = 0;
        
        this.init();
        this.createNodes();
        this.animate();
        this.handleResize();
    }
    
    init() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
        
        // Mouse/touch interaction
        this.mouseX = null;
        this.mouseY = null;
        
        window.addEventListener('resize', () => this.handleResize());
        window.addEventListener('mousemove', (e) => {
            this.mouseX = e.clientX;
            this.mouseY = e.clientY;
        });
        window.addEventListener('mouseleave', () => {
            this.mouseX = null;
            this.mouseY = null;
        });
    }
    
    createNodes() {
        // Create 8-12 network nodes
        const nodeCount = Math.floor(Math.random() * 5) + 8;
        
        for (let i = 0; i < nodeCount; i++) {
            this.nodes.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                radius: Math.random() * 4 + 3,
                vx: (Math.random() - 0.5) * 0.3,
                vy: (Math.random() - 0.5) * 0.3,
                color: `rgba(27, 160, 215, ${Math.random() * 0.3 + 0.2})`
            });
        }
        
        // Create particles
        const particleCount = 80;
        for (let i = 0; i < particleCount; i++) {
            this.particles.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                radius: Math.random() * 2 + 1,
                vx: (Math.random() - 0.5) * 0.5,
                vy: (Math.random() - 0.5) * 0.5,
                alpha: Math.random() * 0.3 + 0.1
            });
        }
    }
    
    handleResize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
        this.nodes = [];
        this.particles = [];
        this.createNodes();
    }
    
    updateParticles() {
        for (let p of this.particles) {
            p.x += p.vx;
            p.y += p.vy;
            
            // Wrap around edges
            if (p.x < 0) p.x = this.canvas.width;
            if (p.x > this.canvas.width) p.x = 0;
            if (p.y < 0) p.y = this.canvas.height;
            if (p.y > this.canvas.height) p.y = 0;
            
            // Mouse attraction/repulsion
            if (this.mouseX && this.mouseY) {
                const dx = p.x - this.mouseX;
                const dy = p.y - this.mouseY;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 150) {
                    const angle = Math.atan2(dy, dx);
                    const force = (150 - dist) / 150 * 0.5;
                    p.x += Math.cos(angle) * force;
                    p.y += Math.sin(angle) * force;
                }
            }
        }
        
        // Update nodes (slow drift)
        for (let n of this.nodes) {
            n.x += n.vx;
            n.y += n.vy;
            
            if (n.x < 0 || n.x > this.canvas.width) n.vx *= -1;
            if (n.y < 0 || n.y > this.canvas.height) n.vy *= -1;
            
            n.x = Math.max(0, Math.min(this.canvas.width, n.x));
            n.y = Math.max(0, Math.min(this.canvas.height, n.y));
        }
        
        // Create links between nearby nodes
        this.links = [];
        for (let i = 0; i < this.nodes.length; i++) {
            for (let j = i + 1; j < this.nodes.length; j++) {
                const dx = this.nodes[i].x - this.nodes[j].x;
                const dy = this.nodes[i].y - this.nodes[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 200) {
                    this.links.push({
                        from: this.nodes[i],
                        to: this.nodes[j],
                        distance: dist,
                        alpha: 1 - (dist / 200)
                    });
                }
            }
        }
    }
    
    draw() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Draw links (data flows)
        for (let link of this.links) {
            this.ctx.beginPath();
            this.ctx.moveTo(link.from.x, link.from.y);
            this.ctx.lineTo(link.to.x, link.to.y);
            
            // Pulsing effect based on time
            const pulse = Math.sin(this.time * 0.003) * 0.3 + 0.3;
            this.ctx.strokeStyle = `rgba(27, 160, 215, ${link.alpha * 0.3 * pulse})`;
            this.ctx.lineWidth = 1;
            this.ctx.stroke();
            
            // Draw data packets along links
            if (Math.random() < 0.02) {
                const t = Math.random();
                const packetX = link.from.x + (link.to.x - link.from.x) * t;
                const packetY = link.from.y + (link.to.y - link.from.y) * t;
                this.ctx.beginPath();
                this.ctx.arc(packetX, packetY, 2, 0, Math.PI * 2);
                this.ctx.fillStyle = `rgba(27, 160, 215, 0.8)`;
                this.ctx.fill();
            }
        }
        
        // Draw nodes
        for (let n of this.nodes) {
            this.ctx.beginPath();
            this.ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
            this.ctx.fillStyle = n.color;
            this.ctx.fill();
            
            // Inner glow
            this.ctx.beginPath();
            this.ctx.arc(n.x, n.y, n.radius * 0.6, 0, Math.PI * 2);
            this.ctx.fillStyle = `rgba(27, 160, 215, 0.6)`;
            this.ctx.fill();
        }
        
        // Draw particles
        for (let p of this.particles) {
            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            this.ctx.fillStyle = `rgba(100, 180, 220, ${p.alpha})`;
            this.ctx.fill();
        }
        
        this.time++;
    }
    
    animate() {
        this.updateParticles();
        this.draw();
        this.animationId = requestAnimationFrame(() => this.animate());
    }
    
    destroy() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
    }
}

// Initialize when DOM loads
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.createElement('canvas');
    canvas.id = 'particles-canvas';
    document.body.insertBefore(canvas, document.body.firstChild);
    
    window.particleSystem = new NetworkParticleSystem(canvas);
});
