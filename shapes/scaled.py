from shape import Shape

class ScaledX(Shape):
    """ An adapter to other shapes that transforms the x input before 
        calling the underlying shape, so the resulting function is
        g(x) = f(s(x))
    """
    def __init__(self, shape, scaler):
        Shape.__init__(self, shape.priors)
        self.shape = shape
        self.scaler = scaler
        
    def n_params(self):
        return self.shape.n_params()

    def cache_name(self):
        return '{}-{}'.format(self.shape.cache_name(), self.scaler.cache_name())

    def format_params(self, theta, latex=False):
        return self.shape.format_params(theta,latex)

    def f(self,theta,x):
        return self.shape.f(theta, self._sx(x))

    def f_grad(self,theta,x):
        return self.shape.f_grad(theta, self._sx(x))
    
    def get_theta_guess(self,x,y):
        return self.shape.get_theta_guess(self._sx(x),y)
    
    def _sx(self, x):
        return self.scaler.scale(x)
